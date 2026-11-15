from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from sqlalchemy import select

from agent.memory.store import Memory
from agent.settings import get_settings
from apps.api.auth import token_store
from apps.api.auth.security import CurrentUser, get_profile
from apps.api.db import SavedSearch, User, session
from apps.api.schemas import (
    Accepted,
    MemoryItem,
    OnboardIn,
    PersonaOut,
    ProfileOut,
    SearchIn,
    SearchOut,
    Settings,
)
from rag.ingest import pipeline
from rag.retriever import owner_index
from worker.engine import engine
from worker.queue import enqueue

router = APIRouter(prefix="/api", tags=["profile"])


def personas() -> dict[str, dict]:
    out = {}
    for p in sorted((get_settings().data_dir / "personas").glob("*/profile.json")):
        d = json.loads(p.read_text()); out[d["persona"]] = d
    return out


def _persona(owner: str) -> dict | None:
    return personas().get(owner)


@router.get("/personas", response_model=list[PersonaOut])
def list_personas(): return [PersonaOut(id=k, **{f: v[f] for f in ("name", "headline", "skills", "floor_rate", "target_rate", "min_project", "categories")}) for k, v in personas().items()]


@router.get("/profile", response_model=ProfileOut)
def get_my_profile(user: User = CurrentUser):
    with session() as s:
        p = get_profile(s, user.id)
        return ProfileOut(owner=p.owner, settings=Settings(**p.settings), upwork_connected=token_store.is_connected(user.id, "upwork"), persona=_persona(p.owner))


@router.put("/profile", response_model=ProfileOut)
def update_settings(body: Settings, user: User = CurrentUser):
    if body.marketplace == "upwork" and not token_store.is_connected(user.id, "upwork"):
        raise HTTPException(409, "Connect your Upwork account before switching to live mode")
    with session() as s:
        p = get_profile(s, user.id); p.settings = {**p.settings, **body.model_dump()}
    return get_my_profile(user)


@router.post("/profile/onboard", response_model=ProfileOut)
async def onboard(body: OnboardIn, user: User = CurrentUser):
    """First run: pick a bundled persona portfolio (or an empty one to upload into), set rates,
    filters and the weekly Connects budget, and create default saved searches."""
    ps = personas()
    owner = body.persona if body.persona in ps else f"own-{user.id}"
    if body.persona not in ps and body.persona != "own": raise HTTPException(422, "Unknown persona")
    if owner.startswith("own-"):
        (get_settings().processed / "uploads" / owner).mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(pipeline.build_index, owner)      # CPU work off the event loop
    with session() as s:
        p = get_profile(s, user.id)
        p.owner, p.settings = owner, {**p.settings, **body.model_dump()["settings"], "onboarded": True}
        if not s.scalars(select(SavedSearch).where(SavedSearch.user_id == user.id)).first():
            cats = body.settings.categories or (ps.get(owner, {}).get("categories") or [None])
            for c in cats: s.add(SavedSearch(user_id=user.id, query="", category=c, interval_minutes=5))
    await enqueue("scout_user", user.id, True, key=f"scout:{user.id}")
    return get_my_profile(user)


# ---- saved searches
@router.get("/searches", response_model=list[SearchOut])
def list_searches(user: User = CurrentUser):
    with session() as s:
        return [SearchOut(id=x.id, query=x.query, category=x.category, interval_minutes=x.interval_minutes, enabled=bool(x.enabled), last_run_at=x.last_run_at)
                for x in s.scalars(select(SavedSearch).where(SavedSearch.user_id == user.id))]


@router.post("/searches", response_model=SearchOut)
def add_search(body: SearchIn, user: User = CurrentUser):
    with session() as s:
        x = SavedSearch(user_id=user.id, **body.model_dump()); s.add(x); s.flush()
        return SearchOut(id=x.id, **body.model_dump())


@router.delete("/searches/{search_id}", response_model=Accepted)
def delete_search(search_id: str, user: User = CurrentUser):
    with session() as s:
        x = s.get(SavedSearch, search_id)
        if not x or x.user_id != user.id: raise HTTPException(404, "Not found")
        s.delete(x)
    return Accepted()


# ---- portfolio
@router.get("/portfolio/items")
def portfolio_items(user: User = CurrentUser) -> list[dict]:
    with session() as s: owner = get_profile(s, user.id).owner
    return [{"id": d.id, "type": d.type, "title": d.title, "skills": d.meta.get("skills") or [], "date": d.meta.get("date", ""), "client_industry": d.meta.get("client_industry", ""),
             "outcome": d.meta.get("outcome", ""), "provenance": d.meta.get("provenance", "")} for d in owner_index(owner).docs.values() if d.type != "proposal"]


@router.post("/portfolio/upload")
async def portfolio_upload(file: UploadFile = File(...), doc_type: str = Form("case_study"), user: User = CurrentUser) -> dict:
    """Add a case study / review / CV (Markdown, text or PDF). Only this document is embedded (incremental re-index)."""
    if doc_type not in ("case_study", "review", "proposal", "upload"): raise HTTPException(422, "Unsupported document type")
    data = await file.read()
    if len(data) > 2_000_000: raise HTTPException(413, "File larger than 2 MB")
    if not (file.filename or "").lower().endswith((".md", ".txt", ".pdf")): raise HTTPException(415, "Upload .md, .txt or .pdf")
    with session() as s: owner = get_profile(s, user.id).owner
    return await asyncio.to_thread(pipeline.add_document, owner, file.filename, data, doc_type)


@router.delete("/portfolio/items/{item_id}", response_model=Accepted)
def portfolio_delete(item_id: str, restore: bool = False, user: User = CurrentUser):
    with session() as s: owner = get_profile(s, user.id).owner
    if not restore and item_id not in owner_index(owner).docs: raise HTTPException(404, "No such portfolio item")
    pipeline.delete_document(owner, item_id, restore=restore)  # small: tombstone + incremental re-index
    return Accepted(detail="Restored and re-indexed" if restore else "Removed from the index. Regenerate a draft and claims that relied on it will be gone.")


# ---- memory
@router.get("/memory", response_model=list[MemoryItem])
async def memory_list(user: User = CurrentUser):
    eng = await engine()
    return [MemoryItem(kind=i["kind"], key=i["key"], description=i.get("description", i["key"]), rule=i.get("rule", "candidate - not used by any agent yet" if "candidates" in i["kind"] or "stats" in i["kind"] else ""),
                       value={k: v for k, v in i.items() if k not in ("kind", "key", "description", "rule")}) for i in await Memory(eng.store, user.id).list_all()]


@router.delete("/memory/{kind}/{key:path}", response_model=Accepted)
async def memory_delete(kind: str, key: str, user: User = CurrentUser):
    if kind not in ("style", "outcome", "style_candidates", "outcome_stats"): raise HTTPException(422, "Unknown memory kind")
    eng = await engine()
    await Memory(eng.store, user.id).delete(kind, key)
    return Accepted(detail="Deleted. It will not be used again.")

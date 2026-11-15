"""Loaders: Markdown case studies / reviews / proposals (with front matter), repo READMEs + code,
PDF CVs, and files the user uploads in the UI. Every Doc carries the metadata B1 asks for:
persona, type, project, skills, date, client_industry and, for proposals, outcome."""
from __future__ import annotations

import json
import re
from pathlib import Path

from agent.settings import get_settings
from rag.schema import Doc
from rag.skills import extract_skills

CODE_EXT = {".py", ".ts", ".tsx", ".js", ".sql", ".r", ".ipynb"}


def parse_front_matter(raw: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n?", raw, re.S)
    if not m: return {}, raw
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            try: meta[k.strip()] = json.loads(v.strip())
            except Exception: meta[k.strip()] = v.strip().strip('"')
    return meta, raw[m.end():]


def read_pdf(path: Path) -> str:
    from pypdf import PdfReader
    return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)


def _doc_from_md(path: Path, owner: str, default_type: str) -> Doc:
    meta, body = parse_front_matter(path.read_text(errors="ignore"))
    meta.setdefault("persona", owner); meta.setdefault("type", default_type)
    meta.setdefault("source", str(path.name))
    if not meta.get("skills") and meta["type"] not in ("review",):
        meta["skills"] = extract_skills(body)          # uploaded docs: tag skills from the lexicon
    title = meta.get("title") or (re.search(r"^#\s+(.+)$", body, re.M) or [None, path.stem])[1]
    return Doc(id=meta.get("id") or f"{owner}-{default_type}-{path.stem}", type=meta["type"], title=title, text=body.strip(), meta=meta)


def owner_dirs(owner: str) -> list[Path]:
    s = get_settings()
    return [d for d in (s.data_dir / "personas" / owner, s.processed / "uploads" / owner) if d.exists()]


def load_corpus(owner: str) -> list[Doc]:
    docs: list[Doc] = []
    for base in owner_dirs(owner):
        for sub, typ in (("case_studies", "case_study"), ("reviews", "review"), ("proposals", "proposal"), ("uploads", "upload")):
            for p in sorted((base / sub).glob("*.md")) if (base / sub).exists() else []:
                docs.append(_doc_from_md(p, owner, typ))
        for p in sorted(base.glob("*.md")):
            docs.append(_doc_from_md(p, owner, "cv" if p.stem.startswith("cv") else "upload"))
        has_cv_md = any(d.type == "cv" for d in docs)
        for p in sorted(base.glob("*.pdf")):
            if p.stem.startswith("cv") and has_cv_md: continue      # same CV, already loaded from Markdown
            text = read_pdf(p)
            docs.append(Doc(id=f"{owner}-pdf-{p.stem}", type="cv" if "cv" in p.stem.lower() else "upload", title=p.stem, text=text,
                            meta={"persona": owner, "type": "cv", "source": p.name, "skills": extract_skills(text), "project": "", "date": "", "client_industry": "", "outcome": ""}))
        for rdir in sorted((base / "repos").iterdir()) if (base / "repos").exists() else []:
            readme = rdir / "README.md"
            if not readme.exists(): continue
            d = _doc_from_md(readme, owner, "repo")
            d.code = "\n\n".join(f"# file: {f.relative_to(rdir)}\n{f.read_text(errors='ignore')[:6000]}" for f in sorted(rdir.rglob("*")) if f.suffix in CODE_EXT)
            if not d.meta.get("skills"): d.meta["skills"] = extract_skills(d.text + "\n" + d.code)
            docs.append(d)
    seen, out = set(), []
    for d in docs:
        if d.id not in seen: seen.add(d.id); out.append(d)
    return out

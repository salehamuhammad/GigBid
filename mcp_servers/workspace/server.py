"""Workspace MCP server (A3): free calendar slots, tentative interview holds, email drafts.

Backed by a local mock (one JSON file per user under data/processed/workspace/) so it runs with
no Google credentials. The agent only ever sees MCP tools, so swapping this file's `Calendar`
class for Google Calendar / Gmail API calls changes nothing upstream. Drafts are never sent.

    python -m mcp_servers.workspace.server --transport http --port 8103
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from agent.settings import get_settings
from mcp_servers.common import AuditLog, Identity, identity, serve

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
IdemKey = Annotated[str, Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:\-]+$")]


class Slot(BaseModel):
    start: str = Field(description="ISO 8601 start, UTC")
    end: str
    label: str


class SlotsResult(BaseModel):
    slots: list[Slot]
    timezone: str = "UTC"
    backend: str = "local-mock"


class HoldResult(BaseModel):
    hold_id: str
    start: str
    end: str
    title: str
    status: str = "tentative"
    idempotent_replay: bool = False


class EmailDraftResult(BaseModel):
    draft_id: str
    subject: str
    status: str = "draft (never sent automatically)"
    idempotent_replay: bool = False


class Calendar:
    def __init__(self, user: str):
        d = get_settings().processed / "workspace"; d.mkdir(parents=True, exist_ok=True)
        self.user, self.path = user, d / f"{user}.json"
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {"holds": {}, "emails": {}, "idem": {}}

    def save(self): self.path.write_text(json.dumps(self.data, indent=1))

    def _busy(self, day: date, hour: int) -> bool:
        """Deterministic pseudo-calendar: roughly 40% of working hours are busy."""
        return int(hashlib.sha1(f"{self.user}{day}{hour}".encode()).hexdigest(), 16) % 10 < 4

    def free_slots(self, start: date, days: int, minutes: int, limit: int) -> list[Slot]:
        out, held = [], {h["start"] for h in self.data["holds"].values()}
        for d in range(days):
            day = start + timedelta(days=d)
            if day.weekday() >= 5: continue
            for hour in range(9, 18):
                st = datetime.combine(day, time(hour), tzinfo=timezone.utc)
                if st <= datetime.now(timezone.utc) or self._busy(day, hour) or st.isoformat() in held: continue
                out.append(Slot(start=st.isoformat(), end=(st + timedelta(minutes=minutes)).isoformat(), label=st.strftime("%a %d %b, %H:%M UTC")))
                if len(out) >= limit: return out
        return out


def build_server(default: Identity | None = None, host: str = "0.0.0.0", port: int = 8103) -> FastMCP:
    mcp = FastMCP("gigbid-workspace", instructions="Calendar slots, tentative interview holds and email drafts for the freelancer. Nothing is sent.", host=host, port=port, stateless_http=True, json_response=True)
    audit = AuditLog("workspace")

    @mcp.tool(annotations=READ, description="Free calendar slots in working hours (UTC) for the next `days` days. Use before offering interview times.")
    async def find_free_slots(ctx: Context, days: Annotated[int, Field(ge=1, le=14)] = 5, duration_minutes: Annotated[int, Field(ge=15, le=120)] = 30,
                              limit: Annotated[int, Field(ge=1, le=10)] = 3, start_date: Annotated[str | None, Field(description="YYYY-MM-DD; default today")] = None) -> SlotsResult:
        ident = identity(ctx, default)
        st = date.fromisoformat(start_date) if start_date else datetime.now(timezone.utc).date()
        res = SlotsResult(slots=Calendar(ident.user).free_slots(st, days, duration_minutes, limit))
        audit.write(ident, "find_free_slots", {"days": days, "duration_minutes": duration_minutes}, {"n": len(res.slots)}); return res

    @mcp.tool(annotations=WRITE, description="Place a TENTATIVE hold on the calendar for an interview. Idempotent per idempotency_key.")
    async def create_interview_hold(ctx: Context, start: Annotated[str, Field(description="ISO 8601 start from find_free_slots")], title: Annotated[str, Field(min_length=3, max_length=120)],
                                    idempotency_key: IdemKey, duration_minutes: Annotated[int, Field(ge=15, le=120)] = 30) -> HoldResult:
        ident, cal = identity(ctx, default), None
        cal = Calendar(ident.user)
        if idempotency_key in cal.data["idem"]:
            return HoldResult(**cal.data["holds"][cal.data["idem"][idempotency_key]], idempotent_replay=True)
        st = datetime.fromisoformat(start)
        hold = {"hold_id": "hold-" + uuid.uuid4().hex[:8], "start": st.isoformat(), "end": (st + timedelta(minutes=duration_minutes)).isoformat(), "title": title, "status": "tentative"}
        cal.data["holds"][hold["hold_id"]] = hold; cal.data["idem"][idempotency_key] = hold["hold_id"]; cal.save()
        audit.write(ident, "create_interview_hold", {"start": start, "title": title}, hold); return HoldResult(**hold)

    @mcp.tool(annotations=WRITE, description="Save an email DRAFT in the freelancer's own mailbox (for example interview notes to self). Never sent. Idempotent per idempotency_key.")
    async def create_email_draft(ctx: Context, subject: Annotated[str, Field(min_length=3, max_length=160)], body: Annotated[str, Field(min_length=1, max_length=6000)], idempotency_key: IdemKey) -> EmailDraftResult:
        ident = identity(ctx, default); cal = Calendar(ident.user)
        if idempotency_key in cal.data["idem"]:
            e = cal.data["emails"][cal.data["idem"][idempotency_key]]; return EmailDraftResult(draft_id=e["draft_id"], subject=e["subject"], idempotent_replay=True)
        e = {"draft_id": "mail-" + uuid.uuid4().hex[:8], "subject": subject, "body": body, "created_at": datetime.now(timezone.utc).isoformat()}
        cal.data["emails"][e["draft_id"]] = e; cal.data["idem"][idempotency_key] = e["draft_id"]; cal.save()
        audit.write(ident, "create_email_draft", {"subject": subject}, {"draft_id": e["draft_id"]}); return EmailDraftResult(draft_id=e["draft_id"], subject=subject)

    @mcp.tool(annotations=READ, description="List tentative holds and saved email drafts.")
    async def list_workspace_items(ctx: Context) -> dict:
        cal = Calendar(identity(ctx, default).user)
        return {"holds": list(cal.data["holds"].values()), "email_drafts": [{k: v for k, v in e.items() if k != "body"} for e in cal.data["emails"].values()]}

    return mcp


def main() -> None:
    serve(build_server(), 8103)


if __name__ == "__main__":
    main()

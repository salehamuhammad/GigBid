"""Create tables, build the RAG indexes for the bundled personas and seed the reviewer account.

    python -m scripts.seed

Set REVIEWER_PASSWORD to provision the optional reviewer account without logging its credential.
"""
from __future__ import annotations

import os

from sqlalchemy import select

from apps.api.auth.security import DEFAULT_SETTINGS, create_user, get_profile
from apps.api.db import SavedSearch, User, engine, session
from apps.api.routers.profile import personas
from rag.ingest.pipeline import build_index


def main() -> None:
    engine()
    for pid in personas():
        print("index:", build_index(pid))
    pw = os.getenv("REVIEWER_PASSWORD")
    if not pw:
        print("Reviewer account provisioning skipped. Set REVIEWER_PASSWORD to enable it.")
        return
    email = os.getenv("REVIEWER_EMAIL", "reviewer@gigbid.dev")
    with session() as s:
        exists = s.scalars(select(User).where(User.email == email)).first()
    if exists:
        print(f"reviewer account already exists: {email}"); return
    p = personas()["ai_engineer"]
    u = create_user(email, pw, "Reviewer", owner="ai_engineer",
                    settings={**DEFAULT_SETTINGS, "floor_rate": p["floor_rate"], "target_rate": p["target_rate"], "min_project": p["min_project"], "onboarded": True})
    with session() as s:
        get_profile(s, u.id)
        for c in p["categories"]: s.add(SavedSearch(user_id=u.id, query="", category=c, interval_minutes=5))
    print("Reviewer account provisioned.")


if __name__ == "__main__":
    main()

async def test_slots_hold_and_email_draft(toolbox):
    slots = await toolbox.call("liaison", "workspace.find_free_slots", {"days": 7, "limit": 3})
    assert len(slots["slots"]) == 3
    h1 = await toolbox.call("liaison", "workspace.create_interview_hold", {"start": slots["slots"][0]["start"], "title": "Interview: RAG project", "idempotency_key": "hold-key-001"})
    h2 = await toolbox.call("liaison", "workspace.create_interview_hold", {"start": slots["slots"][0]["start"], "title": "Interview: RAG project", "idempotency_key": "hold-key-001"})
    assert h1["hold_id"] == h2["hold_id"] and h2["idempotent_replay"] and h1["status"] == "tentative"
    again = await toolbox.call("liaison", "workspace.find_free_slots", {"days": 7, "limit": 3})
    assert slots["slots"][0]["start"] not in [s["start"] for s in again["slots"]]
    d = await toolbox.call("liaison", "workspace.create_email_draft", {"subject": "Interview notes", "body": "Prepare the churn case study.", "idempotency_key": "mail-key-001"})
    assert d["draft_id"].startswith("mail-") and "never sent" in d["status"]

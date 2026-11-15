"""A7: fails CI when an MCP tool signature changes unintentionally.
If the change is intended, regenerate with `python -m scripts.tool_docs` and commit the snapshot."""
import json
from pathlib import Path

from scripts.tool_docs import SNAP, snapshot


async def test_tool_signatures_match_snapshot(toolbox):
    now = snapshot(await toolbox.list_tools())
    old = json.loads(Path(SNAP).read_text())
    drift = sorted(k for k in set(old) | set(now) if old.get(k) != now.get(k))
    assert not drift, f"MCP tool signatures changed: {drift}. If intended, run `python -m scripts.tool_docs` and commit."

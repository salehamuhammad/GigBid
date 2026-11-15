"""Test harness: everything runs in one process with no network.
  - isolated data/processed directory per session
  - GigSim mounted through httpx's ASGI transport (no port)
  - MCP servers reached through the in-memory transport
  - MODEL_PROFILE=offline (deterministic heuristics, hash embeddings)
"""
import os
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_tmp = Path(tempfile.mkdtemp(prefix="gigbid-test-"))
(_tmp / "data").mkdir()
for name in ("personas", "policy_pack", "gigsim", "skills_lexicon.json"):
    src = ROOT / "data" / name
    (shutil.copytree if src.is_dir() else shutil.copy)(src, _tmp / "data" / name)
os.environ.update({"GIGBID_DATA_DIR": str(_tmp / "data"), "MODEL_PROFILE": "offline", "MCP_TRANSPORT": "inprocess", "MARKETPLACE_MODE": "gigsim",
                   "GIGSIM_ERROR_RATE": "0", "GIGSIM_RATE_LIMIT": "100000", "MARKETPLACE_RPM": "100000", "GIGSIM_STATE": str(_tmp / "gigsim_state.json"), "GIGSIM_EVENT_DELAY": "1", "DATABASE_URL": f"sqlite:///{_tmp / 'app.db'}",
                   "APP_SECRET_KEY": "test-secret-key-that-is-long-enough-123456", "REDIS_URL": "", "QDRANT_URL": "", "LANGSMITH_TRACING": "false", "EMBEDDINGS_PROVIDER": "hash", "RERANKER_PROVIDER": "lexical"})

import httpx  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _gigsim():
    from gigsim.app import app
    from mcp_servers.marketplace.adapters import gigsim as adapter
    adapter.set_transport(httpx.ASGITransport(app=app))
    yield
    adapter.set_transport(None)
    shutil.rmtree(_tmp, ignore_errors=True)


@pytest.fixture
def toolbox():
    import uuid

    from agent.mcp_client import ToolBox
    return ToolBox(user="u-" + uuid.uuid4().hex[:8], owner="ai_engineer", trace_id="trace-test")

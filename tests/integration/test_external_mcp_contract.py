from __future__ import annotations

import base64
import hashlib
from contextlib import asynccontextmanager
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from apps.api.auth import token_store, upwork_oauth
from apps.api.db import OAuthToken, session
from mcp_servers.marketplace.adapters.upwork_live import UpworkLiveAdapter
from rag.ingest import github


def test_oauth_pkce_token_exchange_stores_only_ciphertext(monkeypatch):
    issuer = "https://auth.example.test"
    token = "mock-upwork-access-for-contract"
    monkeypatch.setenv("UPWORK_CLIENT_ID", "mock-client")
    monkeypatch.setattr(upwork_oauth, "discover", lambda: {
        "authorization_endpoint": issuer + "/authorize", "token_endpoint": issuer + "/token",
    })
    query = parse_qs(urlparse(upwork_oauth.start("oauth-contract-user")).query)
    state = query["state"][0]
    assert query["code_challenge_method"] == ["S256"]

    def exchange(url, *, data, timeout):
        assert url == issuer + "/token"
        digest = hashlib.sha256(data["code_verifier"].encode()).digest()
        assert query["code_challenge"] == [base64.urlsafe_b64encode(digest).decode().rstrip("=")]
        assert data["code"] == "mock-authorization-code"
        return httpx.Response(200, json={"access_token": token}, request=httpx.Request("POST", url))

    monkeypatch.setattr(upwork_oauth.httpx, "post", exchange)
    assert upwork_oauth.finish(state, "mock-authorization-code") == "oauth-contract-user"
    with session() as db:
        assert token not in db.get(OAuthToken, ("oauth-contract-user", "upwork")).encrypted
    assert token_store.get_access_token("oauth-contract-user", "upwork") == token
    with pytest.raises(RuntimeError, match="Unknown or expired"):
        upwork_oauth.finish(state, "mock-authorization-code")


async def test_upwork_draft_approval_does_not_call_a_remote_submit_tool(monkeypatch):
    adapter = UpworkLiveAdapter("mock-user")
    calls = []

    class Remote:
        async def list_tools(self):
            return SimpleNamespace(tools=[SimpleNamespace(name=adapter.map["create_proposal_draft"])])

        async def call_tool(self, name, params):
            calls.append((name, params))
            return SimpleNamespace(isError=False, structuredContent={"draft_id": "draft-proof-1"})

    @asynccontextmanager
    async def remote(name):
        assert name == "upwork"
        yield Remote()

    monkeypatch.setattr(adapter, "_client", lambda: SimpleNamespace(session=remote))
    draft = await adapter.create_proposal_draft("job-1", "Draft text", 300, [], "draft-key")
    assert draft["draft_id"] == "draft-proof-1"
    assert (await adapter.submit_proposal(draft["draft_id"], "submit-key"))["status"] == "awaiting_confirmation_on_upwork"
    assert [call[0] for call in calls] == [adapter.map["create_proposal_draft"]]


async def test_github_ingest_reads_public_repositories_and_decodes_file_payloads(monkeypatch, tmp_path):
    from langchain_mcp_adapters import client

    monkeypatch.setenv("GITHUB_TOKEN", "mock-token")
    monkeypatch.setattr(github, "get_settings", lambda: SimpleNamespace(processed=tmp_path))
    monkeypatch.setattr(github, "build_index", lambda owner: {"owner": owner})

    class Remote:
        async def list_tools(self):
            return SimpleNamespace(tools=[SimpleNamespace(name=name) for name in github.ALLOWED])

        async def call_tool(self, name, params):
            if name == "search_repositories":
                assert "is:public" in params["query"]
                payload = {"items": [{"name": "public-demo", "private": False}, {"name": "private-demo", "private": True}]}
            else:
                assert params["repo"] == "public-demo"
                path = params["path"]
                if path == "/":
                    payload = {"entries": [{"type": "file", "path": "example.py"}]}
                else:
                    content = "# Project overview" if path == "README.md" else "def run(): pass"
                    payload = {"encoding": "base64", "content": base64.b64encode(content.encode()).decode()}
            return SimpleNamespace(isError=False, structuredContent=payload)

    @asynccontextmanager
    async def remote(name):
        assert name == "github"
        yield Remote()

    monkeypatch.setattr(client, "MultiServerMCPClient", lambda _: SimpleNamespace(session=remote))
    result = await github.ingest("test-owner", "test-user")
    base = tmp_path / "uploads" / "test-owner" / "repos"
    assert result["repos"] == ["public-demo"]
    assert "# Project overview" in (base / "public-demo" / "README.md").read_text(encoding="utf-8")
    assert (base / "public-demo" / "src" / "example.py").read_text(encoding="utf-8") == "def run(): pass"

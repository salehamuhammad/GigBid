"""OAuth 2.1 (authorization code + PKCE) against the official Upwork MCP server, following the MCP
authorization spec: protected-resource metadata -> authorization-server metadata -> dynamic client
registration -> authorize -> token. Tokens go straight into the encrypted store.

STATUS: implements the standard flow; not yet exercised against a real Upwork account in this
repo's first version. If Upwork does not allow dynamic client registration for your app, set
UPWORK_CLIENT_ID (and UPWORK_CLIENT_SECRET if issued) and registration is skipped.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
from urllib.parse import urlencode, urlparse

import httpx

from agent.settings import get_settings
from apps.api.auth.token_store import load_tokens, save_tokens

_pending: dict[str, dict] = {}       # state -> {user_id, verifier, meta, client, at}


def _server_url() -> str:
    return os.getenv("UPWORK_MCP_URL") or get_settings().cfg["marketplace"]["upwork"]["url"]


def _redirect_uri() -> str:
    return os.getenv("UPWORK_REDIRECT_URI", "http://localhost:8000/api/auth/upwork/callback")


def discover() -> dict:
    url = _server_url(); u = urlparse(url); origin = f"{u.scheme}://{u.netloc}"
    with httpx.Client(timeout=15, follow_redirects=True) as c:
        issuer = origin
        for path in (f"/.well-known/oauth-protected-resource{u.path}", "/.well-known/oauth-protected-resource"):
            r = c.get(origin + path)
            if r.status_code == 200 and r.json().get("authorization_servers"):
                issuer = r.json()["authorization_servers"][0].rstrip("/"); break
        iu = urlparse(issuer)
        for path in (f"/.well-known/oauth-authorization-server{iu.path}", "/.well-known/oauth-authorization-server", "/.well-known/openid-configuration"):
            r = c.get(f"{iu.scheme}://{iu.netloc}{path}")
            if r.status_code == 200 and "authorization_endpoint" in r.json(): return r.json()
    raise RuntimeError("Could not discover Upwork's OAuth metadata")


def _client(meta: dict) -> dict:
    if os.getenv("UPWORK_CLIENT_ID"):
        return {"client_id": os.environ["UPWORK_CLIENT_ID"], "client_secret": os.getenv("UPWORK_CLIENT_SECRET")}
    if not meta.get("registration_endpoint"):
        raise RuntimeError("Upwork does not offer dynamic client registration; set UPWORK_CLIENT_ID")
    r = httpx.post(meta["registration_endpoint"], timeout=15, json={"client_name": "GigBid", "redirect_uris": [_redirect_uri()], "grant_types": ["authorization_code", "refresh_token"],
                                                                    "response_types": ["code"], "token_endpoint_auth_method": "none"})
    r.raise_for_status(); return r.json()


def start(user_id: str) -> str:
    """Returns the URL the user must open to authorise GigBid on Upwork."""
    meta = discover(); client = _client(meta)
    verifier = secrets.token_urlsafe(64); state = secrets.token_urlsafe(24)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    _pending[state] = {"user_id": user_id, "verifier": verifier, "meta": meta, "client": client, "at": time.time()}
    q = {"response_type": "code", "client_id": client["client_id"], "redirect_uri": _redirect_uri(), "state": state, "code_challenge": challenge,
         "code_challenge_method": "S256", "resource": _server_url()}
    if meta.get("scopes_supported"): q["scope"] = " ".join(meta["scopes_supported"])
    return meta["authorization_endpoint"] + "?" + urlencode(q)


def finish(state: str, code: str) -> str:
    p = _pending.pop(state, None)
    if not p or time.time() - p["at"] > 900: raise RuntimeError("Unknown or expired OAuth state")
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": _redirect_uri(), "client_id": p["client"]["client_id"], "code_verifier": p["verifier"], "resource": _server_url()}
    if p["client"].get("client_secret"): data["client_secret"] = p["client"]["client_secret"]
    r = httpx.post(p["meta"]["token_endpoint"], data=data, timeout=20); r.raise_for_status()
    save_tokens(p["user_id"], "upwork", {**r.json(), "token_endpoint": p["meta"]["token_endpoint"], "client": p["client"]})
    return p["user_id"]


def refresh(user_id: str, tokens: dict | None = None) -> dict | None:
    t = tokens or load_tokens(user_id, "upwork")
    if not t or not t.get("refresh_token"): return None
    data = {"grant_type": "refresh_token", "refresh_token": t["refresh_token"], "client_id": t["client"]["client_id"]}
    if t["client"].get("client_secret"): data["client_secret"] = t["client"]["client_secret"]
    r = httpx.post(t["token_endpoint"], data=data, timeout=20)
    if r.status_code != 200: return None
    new = {**t, **r.json()}; save_tokens(user_id, "upwork", new); return new

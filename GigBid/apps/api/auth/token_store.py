"""Encrypted OAuth token store (E4): tokens are Fernet-encrypted at rest, one row per
(user, provider), never logged and never returned by any API response."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import time

from cryptography.fernet import Fernet

from agent.settings import get_settings
from apps.api.db import OAuthToken, session


def _fernet() -> Fernet:
    key = os.getenv("TOKEN_ENCRYPTION_KEY")
    if not key:      # derive a stable key from the app secret so local runs work; set a real key in production
        key = base64.urlsafe_b64encode(hashlib.sha256(get_settings().secret.encode()).digest()).decode()
    return Fernet(key)


def save_tokens(user_id: str, provider: str, tokens: dict) -> None:
    tokens = {**tokens, "saved_at": time.time()}
    enc = _fernet().encrypt(json.dumps(tokens).encode()).decode()
    with session() as s:
        row = s.get(OAuthToken, (user_id, provider))
        if row: row.encrypted, row.updated_at = enc, time.time()
        else: s.add(OAuthToken(user_id=user_id, provider=provider, encrypted=enc))


def load_tokens(user_id: str, provider: str) -> dict | None:
    with session() as s:
        row = s.get(OAuthToken, (user_id, provider))
        return json.loads(_fernet().decrypt(row.encrypted.encode())) if row else None


def delete_tokens(user_id: str, provider: str) -> None:
    with session() as s:
        row = s.get(OAuthToken, (user_id, provider))
        if row: s.delete(row)


def is_connected(user_id: str, provider: str) -> bool:
    with session() as s:
        return s.get(OAuthToken, (user_id, provider)) is not None


def get_access_token(user_id: str, provider: str) -> str | None:
    """Current access token, refreshed first when it is about to expire."""
    t = load_tokens(user_id, provider)
    if not t: return None
    if t.get("expires_in") and t.get("refresh_token") and time.time() > t["saved_at"] + float(t["expires_in"]) - 60:
        from apps.api.auth.upwork_oauth import refresh
        t = refresh(user_id, t) or t
    return t.get("access_token")

"""Users and sessions: scrypt password hashes, signed JWT sessions, a `current_user` dependency."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

import jwt
from fastapi import Depends, Header, HTTPException, Query

from agent.settings import get_settings
from apps.api.db import Profile, User, session

DEFAULT_SETTINGS = {"floor_rate": 30, "target_rate": 45, "min_project": 200, "connects_budget_week": 60, "autonomy": "suggest", "strategy": "evidence_first",
                    "categories": [], "min_budget": 0, "marketplace": "gigsim", "onboarded": False, "experiment": False}


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    return base64.b64encode(salt + hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)).decode()


def verify_password(pw: str, stored: str) -> bool:
    raw = base64.b64decode(stored)
    return hmac.compare_digest(raw[16:], hashlib.scrypt(pw.encode(), salt=raw[:16], n=2**14, r=8, p=1, dklen=32))


def make_token(user_id: str, ttl_s: int = 7 * 86400) -> str:
    return jwt.encode({"sub": user_id, "exp": int(time.time()) + ttl_s, "typ": "session"}, get_settings().secret, algorithm="HS256")


def current_user(authorization: str = Header(default=""), token: str | None = Query(default=None)) -> User:
    """Bearer header, or `?token=` for EventSource (which cannot set headers)."""
    raw = authorization.split(" ", 1)[1] if authorization.lower().startswith("bearer ") else token
    if not raw: raise HTTPException(401, "Not signed in")
    try:
        claims = jwt.decode(raw, get_settings().secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Session expired or invalid") from None
    with session() as s:
        u = s.get(User, claims["sub"])
    if not u: raise HTTPException(401, "Unknown user")
    return u


CurrentUser = Depends(current_user)


def get_profile(s, user_id: str) -> Profile:
    p = s.get(Profile, user_id)
    if p is None:
        p = Profile(user_id=user_id, owner="ai_engineer", settings=dict(DEFAULT_SETTINGS)); s.add(p); s.flush()
    return p


def create_user(email: str, password: str, name: str = "", owner: str | None = None, settings: dict | None = None) -> User:
    with session() as s:
        if s.query(User).filter(User.email == email.lower()).first():
            raise HTTPException(409, "An account with this email already exists")
        u = User(email=email.lower(), name=name or email.split("@")[0], password_hash=hash_password(password))
        s.add(u); s.flush()
        s.add(Profile(user_id=u.id, owner=owner or "ai_engineer", settings={**DEFAULT_SETTINGS, **(settings or {})}))
        return u

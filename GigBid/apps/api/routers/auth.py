from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from apps.api.auth import token_store, upwork_oauth
from apps.api.auth.security import CurrentUser, create_user, get_profile, make_token, verify_password
from apps.api.db import User, session
from apps.api.schemas import Accepted, Credentials, Session, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _out(u: User) -> UserOut:
    with session() as s:
        return UserOut(id=u.id, email=u.email, name=u.name, onboarded=bool(get_profile(s, u.id).settings.get("onboarded")))


@router.post("/register", response_model=Session)
def register(body: Credentials):
    u = create_user(body.email, body.password, body.name)
    return Session(token=make_token(u.id), user=_out(u))


@router.post("/login", response_model=Session)
def login(body: Credentials):
    with session() as s:
        u = s.query(User).filter(User.email == body.email.lower()).first()
    if not u or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "Wrong email or password")
    return Session(token=make_token(u.id), user=_out(u))


@router.get("/me", response_model=UserOut)
def me(user: User = CurrentUser): return _out(user)


@router.get("/upwork/start")
def upwork_start(user: User = CurrentUser) -> dict:
    """Begin OAuth 2.1 with the official Upwork MCP server. Returns the URL to open."""
    try: return {"authorize_url": upwork_oauth.start(user.id)}
    except Exception as e: raise HTTPException(502, f"Could not start Upwork authorisation: {e}") from e


@router.get("/upwork/callback", include_in_schema=False)
def upwork_callback(state: str, code: str):
    try: upwork_oauth.finish(state, code)
    except Exception as e: raise HTTPException(400, f"Upwork authorisation failed: {e}") from e
    return RedirectResponse("/settings?upwork=connected")


@router.delete("/upwork", response_model=Accepted)
def upwork_disconnect(user: User = CurrentUser):
    token_store.delete_tokens(user.id, "upwork"); return Accepted(detail="Upwork disconnected; stored tokens deleted")

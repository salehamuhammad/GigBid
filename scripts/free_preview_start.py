"""Start the disposable Render preview with deterministic models and embedded GigSim."""
from __future__ import annotations

import os
import secrets


def main() -> None:
    os.environ["MODEL_PROFILE"] = "offline"
    os.environ["MARKETPLACE_MODE"] = "gigsim"
    os.environ["MCP_TRANSPORT"] = "inprocess"
    os.environ["GIGBID_EMBED_GIGSIM"] = "1"
    os.environ.setdefault("APP_SECRET_KEY", secrets.token_urlsafe(48))
    os.environ.setdefault("GIGSIM_API_TOKEN", secrets.token_urlsafe(32))
    os.environ.setdefault("GIGSIM_BASE_URL", "http://gigsim.internal")
    os.environ.setdefault("GIGSIM_STATE", "/app/data/processed/gigsim_state.json")
    os.environ.setdefault("GIGSIM_ERROR_RATE", "0")
    os.environ.setdefault("GIGSIM_EVENT_DELAY", "3")
    os.environ.setdefault("GIGSIM_RATE_LIMIT", "300")
    os.environ.setdefault("MARKETPLACE_RPM", "240")
    os.environ.setdefault("GIGBID_TICK_SECONDS", "30")
    for key in ("REDIS_URL", "QDRANT_URL", "GROQ_API_KEY"):
        os.environ.pop(key, None)
    from scripts.seed import main as seed

    seed()
    import uvicorn

    uvicorn.run("apps.api.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))


if __name__ == "__main__":
    main()

"""Configuration loader. One place reads agent/config.yaml and the environment."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


class Settings:
    def __init__(self) -> None:
        self.cfg: dict[str, Any] = yaml.safe_load((ROOT / "agent" / "config.yaml").read_text())
        if os.getenv("MARKETPLACE_RPM"): self.cfg["marketplace"]["max_requests_per_minute"] = int(os.environ["MARKETPLACE_RPM"])
        self.root = ROOT
        self.data_dir = Path(os.getenv("GIGBID_DATA_DIR", ROOT / "data"))
        self.processed = self.data_dir / "processed"
        self.processed.mkdir(parents=True, exist_ok=True)

    # ---- environment
    @property
    def secret(self) -> str: return os.getenv("APP_SECRET_KEY") or "dev-only-secret-change-me-32-bytes-min"
    @property
    def database_url(self) -> str:
        url = os.getenv("DATABASE_URL") or f"sqlite:///{self.processed / 'gigbid.db'}"
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url
    @property
    def redis_url(self) -> str | None: return os.getenv("REDIS_URL") or None
    @property
    def qdrant_url(self) -> str | None:
        url = os.getenv("QDRANT_URL")
        if url and not url.startswith(("http://", "https://")):
            return "http://" + url
        return url or None
    @property
    def marketplace_mode(self) -> str: return os.getenv("MARKETPLACE_MODE") or self.cfg["marketplace"]["mode"]
    @property
    def gigsim_url(self) -> str: return os.getenv("GIGSIM_BASE_URL", "http://localhost:8081")
    @property
    def gigsim_token(self) -> str: return os.getenv("GIGSIM_API_TOKEN", "gigsim-dev-token")
    @property
    def mcp_transport(self) -> str: return os.getenv("MCP_TRANSPORT", "inprocess")
    @property
    def profile_name(self) -> str: return os.getenv("MODEL_PROFILE") or self.cfg["models"]["profile"]
    @property
    def profile(self) -> dict[str, Any]: return self.cfg["models"]["profiles"][self.profile_name]
    @property
    def is_postgres(self) -> bool: return self.database_url.startswith("postgres")

    def pg_dsn(self) -> str:
        """psycopg-style DSN for LangGraph's Postgres checkpointer/store."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://")

    def get(self, *path: str, default: Any = None) -> Any:
        cur: Any = self.cfg
        for p in path:
            if not isinstance(cur, dict) or p not in cur:
                return default
            cur = cur[p]
        return cur


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()

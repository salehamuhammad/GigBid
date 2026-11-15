import pytest

from agent.settings import get_settings


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+psycopg"])
def test_render_postgres_uses_the_installed_psycopg_driver(monkeypatch, scheme):
    monkeypatch.setenv("DATABASE_URL", f"{scheme}://user:password@database/gigbid")
    assert get_settings().database_url == "postgresql+psycopg://user:password@database/gigbid"
    assert get_settings().pg_dsn() == "postgresql://user:password@database/gigbid"


def test_render_private_qdrant_address(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "gigbid-vectors:6333")
    assert get_settings().qdrant_url == "http://gigbid-vectors:6333"
    monkeypatch.setenv("QDRANT_URL", "https://vectors.example")
    assert get_settings().qdrant_url == "https://vectors.example"

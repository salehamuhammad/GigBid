"""Ingest a user's public GitHub repositories through the third-party GitHub MCP server (A5).

    python -m rag.ingest.github --owner own-<user_id> --github-user psf --repository requests \
        --branch main --source-path src/requests/api.py

Uses GitHub's remote MCP server over Streamable HTTP with a personal access token (GITHUB_TOKEN,
read-only public scope is enough). Only two read tools are used -- `search_repositories` and
`get_file_contents` -- selected by name; nothing is written to GitHub. Each repo lands under
data/processed/uploads/<owner>/repos/<repo>/ as README.md + a few source files, then the index
is rebuilt incrementally.

Network verification requires a GitHub credential. Use `--list-tools` to inspect the server's
tool names if the published interface changes.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import json
import os
import re

from agent.settings import get_settings
from rag.ingest.pipeline import build_index

URL = os.getenv("GITHUB_MCP_URL", "https://api.githubcopilot.com/mcp/")
ALLOWED = {"search_repositories", "get_file_contents"}
CODE = re.compile(r"\.(py|ts|tsx|js|sql|ipynb|r)$", re.I)
IDENTIFIER = re.compile(r"[\w.-]+", re.ASCII)


def _text(res) -> str:
    resources = [c.resource for c in res.content if getattr(c, "type", None) == "resource"]
    if resources:
        return "\n".join(part for r in resources if (part := getattr(r, "text", None)))
    return "\n".join(getattr(c, "text", "") for c in res.content)


def _payload(result):
    if result.isError:
        raise RuntimeError("GitHub MCP returned a tool error")
    if result.structuredContent is not None:
        return result.structuredContent
    text = _text(result)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _file(result) -> str:
    if result.isError:
        return ""
    payload = _payload(result)
    if isinstance(payload, dict):
        content = payload.get("content")
        if isinstance(content, str) and payload.get("encoding") == "base64":
            try:
                return base64.b64decode(content).decode("utf-8")
            except (UnicodeError, binascii.Error):
                return ""
        return content if isinstance(content, str) else ""
    return payload if isinstance(payload, str) else ""


async def ingest(owner: str, github_user: str, max_repos: int = 8, list_tools: bool = False, *,
                 repository: str | None = None, branch: str | None = None, source_paths: tuple[str, ...] = ()) -> dict:
    from langchain_mcp_adapters.client import MultiServerMCPClient
    if not IDENTIFIER.fullmatch(owner) or owner in (".", ".."):
        raise ValueError("Invalid portfolio owner")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]{0,38}", github_user) or not 1 <= max_repos <= 100:
        raise ValueError("Use a GitHub account name and 1–100 repositories")
    if repository and (not IDENTIFIER.fullmatch(repository) or repository in (".", "..")):
        raise ValueError("Invalid GitHub repository name")
    if (branch or source_paths) and not repository:
        raise ValueError("A branch or explicit source paths require a repository")
    if len(source_paths) > 4 or len({os.path.basename(p) for p in source_paths}) != len(source_paths):
        raise ValueError("Specify up to four source paths with distinct file names")
    if any(not CODE.search(p) or "\\" in p or any(part in ("", ".", "..") for part in p.split("/"))
           for p in source_paths):
        raise ValueError("Use relative repository paths for source files")
    token = os.getenv("GITHUB_TOKEN")
    if not token: raise SystemExit("Set GITHUB_TOKEN (a read-only personal access token).")
    headers = {"Authorization": f"Bearer {token}", "X-MCP-Readonly": "true"}
    client = MultiServerMCPClient({"github": {"transport": "streamable_http", "url": URL, "headers": headers}})
    base = get_settings().processed / "uploads" / owner / "repos"
    done = []
    async with client.session("github") as s:
        names = {t.name for t in (await s.list_tools()).tools}
        if list_tools: return {"tools": sorted(names)}
        missing = ALLOWED - names
        if missing: raise SystemExit(f"GitHub MCP server lacks {missing}; available: {sorted(names)[:30]}")
        query = f"repo:{github_user}/{repository} is:public" if repository else f"user:{github_user} fork:false is:public"
        found = _payload(await s.call_tool("search_repositories", {"query": query, "perPage": 1 if repository else max_repos}))
        if not isinstance(found, dict) or not isinstance(found.get("items"), list):
            raise RuntimeError("GitHub MCP repository search returned an unexpected payload")
        for repo in (found.get("items") or [])[:max_repos]:
            name = repo["name"]
            if repo.get("private") or not IDENTIFIER.fullmatch(name) or name in (".", ".."):
                continue
            if repository and name.casefold() != repository.casefold():
                continue
            params = {"owner": github_user, "repo": name}
            if branch:
                params["ref"] = f"refs/heads/{branch}"
            readme = _file(await s.call_tool("get_file_contents", {**params, "path": "README.md"}))
            if repository and not readme:
                raise RuntimeError("GitHub MCP did not return README.md for the requested repository")
            files = list(source_paths)
            if not files:
                result = await s.call_tool("get_file_contents", {**params, "path": "/"})
                listing = _payload(result) if not result.isError else []
                if isinstance(listing, dict):
                    listing = listing.get("entries", [])
                if isinstance(listing, list):
                    files = [f["path"] for f in listing if f.get("type") == "file" and CODE.search(f["path"])]
            sources = {}
            for path in files[:4]:
                content = _file(await s.call_tool("get_file_contents", {**params, "path": path}))
                if not content and path in source_paths:
                    raise RuntimeError(f"GitHub MCP did not return the requested source file: {path}")
                if content:
                    sources[path] = content
            rdir = base / name; (rdir / "src").mkdir(parents=True, exist_ok=True)
            meta = {"id": f"{owner}-gh-{name}", "type": "repo", "persona": owner, "project": name, "title": f"{name} (GitHub repository)", "date": (repo.get("updated_at") or "")[:10],
                    "client_industry": "", "outcome": "", "provenance": f"github:{github_user}/{name}"}
            (rdir / "README.md").write_text("---\n" + "\n".join(f"{k}: {json.dumps(v)}" for k, v in meta.items()) + "\n---\n\n" + (readme or repo.get("description") or name), encoding="utf-8")
            for path, content in sources.items():
                (rdir / "src" / os.path.basename(path)).write_text(content[:8000], encoding="utf-8")
            done.append(name)
    if repository and not done:
        raise RuntimeError("GitHub MCP did not find the requested public repository")
    return {"repos": done, "index": build_index(owner)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", required=True); ap.add_argument("--github-user", required=True); ap.add_argument("--max-repos", type=int, default=8); ap.add_argument("--list-tools", action="store_true")
    ap.add_argument("--repository")
    ap.add_argument("--branch")
    ap.add_argument("--source-path", action="append", default=[])
    a = ap.parse_args()
    print(json.dumps(asyncio.run(ingest(a.owner, a.github_user, a.max_repos, a.list_tools, repository=a.repository,
                                       branch=a.branch, source_paths=tuple(a.source_path))), indent=2))

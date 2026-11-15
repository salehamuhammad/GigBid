"""Static checks run by CI (F):
  1. no prompt text inline in agent code (prompts live in agent/prompts/*.md, loaded by name);
  2. no model ids hard-coded in Python (models come from agent/config.yaml);
  3. no secrets committed;
  4. every agent node is wired to a prompt file that exists and carries a version.
Exit code 1 on any finding.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = [p for d in ("agent", "apps/api", "rag", "mcp_servers", "worker", "evals", "gigsim") for p in (ROOT / d).rglob("*.py")]
PROMPT = re.compile(r"[\"'](You are (a|an|the) [^\"']{40,}|Return ONLY[^\"']{60,}|## SYSTEM)", re.I)
MODEL = re.compile(r"[\"'](gpt-[\w.\-]+|openai/gpt-oss[\w\-]*|llama-[\d.]+[\w\-]*|qwen[\w:.\-]+|claude-[\w\-]+|gemini-[\w.\-]+|mixtral[\w\-]*)[\"']")
SECRET = re.compile(r"(gsk_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_\-]{20,}|ghp_[A-Za-z0-9]{20,}|lsv2_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)")


def main() -> int:
    bad = []
    for p in PY:
        text = p.read_text(encoding="utf-8"); rel = p.relative_to(ROOT)
        if str(rel).startswith(("agent", "apps", "worker", "rag")) and rel.name != "llm.py":
            bad += [f"inline prompt: {rel}: {m.group(0)[:60]}" for m in PROMPT.finditer(text)]
            bad += [f"hard-coded model: {rel}: {m.group(1)}" for m in MODEL.finditer(text)]
    for p in ROOT.rglob("*"):
        if p.is_file() and p.stat().st_size < 400_000 and not any(x in p.parts for x in ("node_modules", ".git", ".next", "processed", ".venv", ".npm-cache", "artifacts", "playwright-report", "test-results")) and p.suffix not in (".png", ".pdf", ".ico", ".sqlite", ".npy", ".gif"):
            if SECRET.search(p.read_text(encoding="utf-8", errors="ignore")): bad.append(f"possible secret: {p.relative_to(ROOT)}")
    if (ROOT / ".env").exists() and ".env" not in (ROOT / ".gitignore").read_text(encoding="utf-8"): bad.append(".env is not git-ignored")
    for p in (ROOT / "agent" / "prompts").glob("*.md"):
        t = p.read_text(encoding="utf-8")
        if not re.search(r"^version:\s*\S+", t, re.M) or "## SYSTEM" not in t or "## USER" not in t: bad.append(f"prompt file malformed: {p.name}")
    used = {m for f in (ROOT / "agent").rglob("*.py") for m in re.findall(r"n\.llm\(\s*\"\w+\",\s*\"(\w+)\"", f.read_text(encoding="utf-8"))}
    bad += [f"prompt file missing: {u}.md" for u in used if not (ROOT / "agent" / "prompts" / f"{u}.md").exists()]
    for b in bad: print("FAIL", b)
    print(f"ci_checks: {len(PY)} python files, {len(used)} prompts in use, {len(bad)} finding(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

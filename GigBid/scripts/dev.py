"""Start the whole product locally without Docker.

    python -m scripts.dev            # GigSim :8081, API :8000 (worker + MCP servers in-process), web :3000
    MCP_TRANSPORT=http python -m scripts.dev   # also start the three MCP servers on :8101-8103

Ctrl+C stops everything. Works on Windows, macOS and Linux.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def main() -> None:
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONUNBUFFERED": "1"}
    procs = [("gigsim", [PY, "-m", "uvicorn", "gigsim.app:app", "--port", "8081", "--log-level", "warning"])]
    if os.getenv("MCP_TRANSPORT") == "http":
        for name, port in (("portfolio", 8101), ("marketplace", 8102), ("workspace", 8103)):
            procs.append((f"mcp-{name}", [PY, "-m", f"mcp_servers.{name}.server", "--transport", "http", "--port", str(port)]))
    procs.append(("api", [PY, "-m", "uvicorn", "apps.api.main:app", "--port", "8000"]))
    web = ROOT / "apps" / "web"
    npm = shutil.which("npm")
    if npm and (web / "node_modules").exists():
        procs.append(("web", [npm, "run", "dev"]))
    else:
        print("web: skipped (run `make web-install` first, then start this script again)")
    running = []
    try:
        for name, cmd in procs:
            running.append((name, subprocess.Popen(cmd, cwd=web if name == "web" else ROOT, env=env)))
            print(f"started {name}"); time.sleep(1.5 if name == "gigsim" else 0.5)
        print("\nGigBid: http://localhost:3000   API docs: http://localhost:8000/docs   GigSim: http://localhost:8081/docs\n")
        while all(p.poll() is None for _, p in running): time.sleep(1)
        for name, p in running:
            if p.poll() is not None: print(f"{name} exited with code {p.returncode}")
    except KeyboardInterrupt:
        pass
    finally:
        for _, p in running:
            if p.poll() is None: p.terminate()


if __name__ == "__main__":
    main()

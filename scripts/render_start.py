"""Supervise GigBid's API, queue worker, GigSim and HTTP MCP processes on Render."""
from __future__ import annotations

import os
import pwd
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    data = Path("/app/data/processed")
    data.mkdir(parents=True, exist_ok=True)
    if os.getuid() == 0:
        account = pwd.getpwnam("app")
        os.chown(data, account.pw_uid, account.pw_gid)
        os.initgroups(account.pw_name, account.pw_gid)
        os.setgid(account.pw_gid)
        os.setuid(account.pw_uid)
        os.environ["HOME"] = account.pw_dir
    children: list[subprocess.Popen] = []
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    def start(args):
        child = subprocess.Popen(args)
        children.append(child)
        return child

    def wait_port(port):
        deadline = time.monotonic() + 90
        while not stopping and time.monotonic() < deadline:
            if any(child.poll() is not None for child in children):
                raise RuntimeError("A GigBid process exited during startup")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    return
            except OSError:
                time.sleep(.5)
        raise RuntimeError(f"GigBid startup did not reach port {port}")

    try:
        seed = start([sys.executable, "-m", "scripts.seed"])
        if seed.wait() != 0 or stopping:
            return 1
        children.remove(seed)
        start([sys.executable, "-m", "uvicorn", "gigsim.app:app", "--host", "127.0.0.1", "--port", "8081"])
        wait_port(8081)
        for name, port in (("portfolio", 8101), ("marketplace", 8102), ("workspace", 8103)):
            start([sys.executable, "-m", f"mcp_servers.{name}.server", "--transport", "http", "--port", str(port)])
            wait_port(port)
        start([sys.executable, "-m", "arq", "worker.main.WorkerSettings"])
        start([sys.executable, "-m", "uvicorn", "apps.api.main:app", "--host", "0.0.0.0",
               "--port", os.environ.get("PORT", "10000")])
        while not stopping:
            if any(child.poll() is not None for child in children):
                return 1
            time.sleep(1)
        return 0
    finally:
        stop(None, None)
        deadline = time.monotonic() + 25
        for child in reversed(children):
            try:
                child.wait(timeout=max(.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Regression test for concurrent first-load localization requests."""
from __future__ import annotations
import sys

import json
import os
import sqlite3
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from backend_smoke_test import call, expect, free_port, make_client

ROOT = Path(__file__).resolve().parent


def main() -> None:
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="axiom-fleet-phase3-concurrency-", ignore_cleanup_errors=True) as temp_dir:
        db_path = Path(temp_dir) / "axiom.sqlite3"
        env = os.environ.copy()
        env.update({"AXIOM_ENV": "development", "AXIOM_ALLOW_DEMO_ACCOUNT": "0", "PORT": str(port), "AXIOM_DB_PATH": str(db_path)})
        process = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(60):
                try:
                    status, _ = call(make_client(base)[1], base, "GET", "/api/health")
                    if status == 200:
                        break
                except Exception:
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("phase3 concurrency server did not start")

            jar, opener = make_client(base)
            status, signup = call(opener, base, "POST", "/api/auth/signup", {
                "role": "vendor",
                "full_name": "Concurrency Operator",
                "email": "phase3-concurrency@example.com",
                "password": "StrongPass123!",
                "organization_name": "Concurrency Fleet",
                "city": "Bengaluru",
                "timezone": "Asia/Kolkata",
            })
            expect(status == 201 and signup["user"]["organization"]["name"] == "Concurrency Fleet", "concurrency test tenant is isolated")
            cookie = "; ".join(f"{item.name}={item.value}" for item in jar)
            paths = [
                "/api/phase3/sustainability/summary",
                "/api/phase3/sustainability/report",
                "/api/phase3/localization",
                "/api/phase3/regions?limit=20",
            ] * 12

            def get(path: str) -> int:
                request = urllib.request.Request(f"{base}{path}", headers={"Cookie": cookie})
                try:
                    with urllib.request.urlopen(request, timeout=10) as response:
                        response.read()
                        return response.status
                except urllib.error.HTTPError as error:
                    error.read()
                    return error.code

            with ThreadPoolExecutor(max_workers=24) as pool:
                statuses = list(pool.map(get, paths))
            expect(all(status == 200 for status in statuses), f"concurrent Phase 3 first-load requests remain successful ({len(statuses)} responses)")

            with sqlite3.connect(db_path) as conn:
                regions = conn.execute("SELECT COUNT(*) FROM phase3_regions WHERE organization_id = ?", (signup["user"]["organization"]["id"],)).fetchone()[0]
                defaults = conn.execute("SELECT COUNT(*) FROM phase3_regions WHERE organization_id = ? AND is_default = 1", (signup["user"]["organization"]["id"],)).fetchone()[0]
            expect(regions == 1 and defaults == 1, "concurrent localization creates one active default region")
            print("RESULT Phase 3 concurrency test passed")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
            if process.stdout:
                process.stdout.close()


if __name__ == "__main__":
    main()

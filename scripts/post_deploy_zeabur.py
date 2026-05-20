#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path


DEFAULT_SERVICE_ID = "6a0c6dcf40a883532f331aa2"
DEFAULT_ENV_ID = "6a0c6dcef3b70f2a79fbd6f2"
DEFAULT_BASE_URL = "https://linebotqa.zeabur.app"


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("CI", "1")
    proc = subprocess.run(cmd, text=True, capture_output=True, env=env, check=False)
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(cmd)}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return proc


def run_stream(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, text=True, env={**os.environ, "CI": "1"}, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}")


def service_status(service_id: str, env_id: str) -> str:
    proc = run(
        [
            "npx",
            "zeabur",
            "--interactive=false",
            "service",
            "get",
            "--id",
            service_id,
            "--env-id",
            env_id,
            "--json",
        ],
        check=False,
    )
    text = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode != 0:
        return f"unknown:{proc.returncode}"
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        upper = text.upper()
        if "RUNNING" in upper:
            return "RUNNING"
        if "BUILD" in upper:
            return "BUILDING"
        if "DEPLOY" in upper:
            return "DEPLOYING"
        return "unknown"
    if isinstance(payload, dict):
        for key in ("status", "Status", "state", "State"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value.upper()
        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("status", "Status", "state", "State"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    return value.upper()
    return "unknown"


def wait_for_running(service_id: str, env_id: str, timeout_seconds: int, interval_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_status = ""
    while time.monotonic() < deadline:
        status = service_status(service_id, env_id)
        if status != last_status:
            print(f"service_status={status}")
            last_status = status
        if status == "RUNNING":
            return
        time.sleep(interval_seconds)
    raise TimeoutError(f"service did not reach RUNNING within {timeout_seconds}s; last_status={last_status}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Post-deploy Zeabur checklist: wait, sync LLM Wiki, reload, optionally smoke-test.")
    parser.add_argument("--service-id", default=os.getenv("ZEABUR_SERVICE_ID", DEFAULT_SERVICE_ID))
    parser.add_argument("--env-id", default=os.getenv("ZEABUR_ENV_ID", DEFAULT_ENV_ID))
    parser.add_argument("--base-url", default=os.getenv("LINEBOT_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("ZEABUR_WAIT_TIMEOUT", "600")))
    parser.add_argument("--interval", type=int, default=int(os.getenv("ZEABUR_WAIT_INTERVAL", "10")))
    parser.add_argument("--skip-wait", action="store_true")
    parser.add_argument("--skip-sync", action="store_true")
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--sync-extra-args", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    if not args.skip_wait:
        wait_for_running(args.service_id, args.env_id, args.timeout, args.interval)

    if not args.skip_sync:
        sync_cmd = [
            sys.executable,
            str(repo_root / "scripts" / "sync_wiki_to_zeabur.py"),
            "--service-id",
            args.service_id,
            "--env-id",
            args.env_id,
        ]
        if args.reload:
            sync_cmd.append("--reload")
        if args.sync_extra_args:
            sync_cmd.extend(shlex.split(args.sync_extra_args))
        run_stream(sync_cmd)

    if args.smoke:
        run_stream(
            [
                sys.executable,
                str(repo_root / "scripts" / "retrieval_smoke_tests.py"),
                "--base-url",
                args.base_url.rstrip("/"),
                "--sleep",
                "0.05",
            ]
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

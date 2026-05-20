#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_SERVICE_ID = "6a0c6dcf40a883532f331aa2"
DEFAULT_ENV_ID = "6a0c6dcef3b70f2a79fbd6f2"
DEFAULT_BASE_URL = "https://linebotqa.zeabur.app"
DEFAULT_LOCAL_WIKI = Path("/Users/ander/Documents/hermes-agent/wiki/ada-kdigo-diabetes-wiki")


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


def expected_version_from_app(repo_root: Path) -> str:
    app_py = repo_root / "app.py"
    if not app_py.exists():
        return ""
    match = re.search(r'APP_VERSION\s*=\s*os\.getenv\("APP_VERSION",\s*"([^"]+)"\)', app_py.read_text())
    return match.group(1) if match else ""


def get_health(base_url: str, timeout_seconds: int = 30) -> dict[str, object]:
    with urllib.request.urlopen(base_url.rstrip("/") + "/", timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    return payload if isinstance(payload, dict) else {}


def nested_int(payload: dict[str, object], *path: str) -> int:
    value: object = payload
    for key in path:
        if not isinstance(value, dict):
            return 0
        value = value.get(key)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def wiki_files_loaded(payload: dict[str, object]) -> int:
    return max(
        nested_int(payload, "features", "llm_wiki_files"),
        nested_int(payload, "knowledge", "llm_wiki_files"),
    )


def knowledge_available(payload: dict[str, object]) -> bool:
    knowledge = payload.get("knowledge")
    return bool(isinstance(knowledge, dict) and knowledge.get("available"))


def wait_for_health_version(
    base_url: str,
    expected_version: str,
    timeout_seconds: int,
    interval_seconds: int,
    stable_checks: int,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    stable = 0
    last_seen = ""
    last_payload: dict[str, object] = {}
    while time.monotonic() < deadline:
        try:
            payload = get_health(base_url)
            version = str(payload.get("app_version") or "")
            available = knowledge_available(payload)
            wiki_files = wiki_files_loaded(payload)
            seen = f"version={version} available={available} llm_wiki_files={wiki_files}"
            if seen != last_seen:
                print(f"health={seen}")
                last_seen = seen
            if payload.get("ok") and (not expected_version or version == expected_version):
                stable += 1
                last_payload = payload
                if stable >= stable_checks:
                    return payload
            else:
                stable = 0
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            print(f"health_wait={type(exc).__name__}: {exc}")
            stable = 0
        time.sleep(interval_seconds)
    if expected_version:
        raise TimeoutError(
            f"health did not stabilize on app_version={expected_version}; last={last_seen or last_payload}"
        )
    raise TimeoutError(f"health did not stabilize; last={last_seen or last_payload}")


def wait_for_wiki_loaded(
    base_url: str,
    expected_version: str,
    min_wiki_files: int,
    timeout_seconds: int,
    interval_seconds: int,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    last_seen = ""
    while time.monotonic() < deadline:
        try:
            payload = get_health(base_url)
            version = str(payload.get("app_version") or "")
            available = knowledge_available(payload)
            wiki_files = wiki_files_loaded(payload)
            seen = f"version={version} available={available} llm_wiki_files={wiki_files}"
            if seen != last_seen:
                print(f"wiki_verify={seen}")
                last_seen = seen
            if (
                payload.get("ok")
                and available
                and wiki_files >= min_wiki_files
                and (not expected_version or version == expected_version)
            ):
                return payload
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            print(f"wiki_verify_wait={type(exc).__name__}: {exc}")
        time.sleep(interval_seconds)
    raise TimeoutError(f"wiki did not load with >= {min_wiki_files} files; last={last_seen}")


def sync_command(repo_root: Path, args: argparse.Namespace) -> list[str]:
    cmd = [
        sys.executable,
        str(repo_root / "scripts" / "sync_wiki_to_zeabur.py"),
        "--service-id",
        args.service_id,
        "--env-id",
        args.env_id,
        "--local-wiki",
        str(args.local_wiki),
    ]
    if args.reload:
        cmd.append("--reload")
    if args.sync_extra_args:
        cmd.extend(shlex.split(args.sync_extra_args))
    return cmd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Post-deploy Zeabur checklist: wait for the new app, sync LLM Wiki, reload, verify, optionally smoke-test."
    )
    parser.add_argument("--service-id", default=os.getenv("ZEABUR_SERVICE_ID", DEFAULT_SERVICE_ID))
    parser.add_argument("--env-id", default=os.getenv("ZEABUR_ENV_ID", DEFAULT_ENV_ID))
    parser.add_argument("--base-url", default=os.getenv("LINEBOT_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--local-wiki", type=Path, default=Path(os.getenv("LOCAL_WIKI_PATH", DEFAULT_LOCAL_WIKI)))
    parser.add_argument("--expected-version", default=os.getenv("EXPECTED_APP_VERSION", ""))
    parser.add_argument("--min-wiki-files", type=int, default=int(os.getenv("MIN_LLM_WIKI_FILES", "0")))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("ZEABUR_WAIT_TIMEOUT", "600")))
    parser.add_argument("--interval", type=int, default=int(os.getenv("ZEABUR_WAIT_INTERVAL", "10")))
    parser.add_argument("--health-stable-checks", type=int, default=int(os.getenv("ZEABUR_HEALTH_STABLE_CHECKS", "2")))
    parser.add_argument("--verify-timeout", type=int, default=int(os.getenv("ZEABUR_VERIFY_TIMEOUT", "360")))
    parser.add_argument("--resync-attempts", type=int, default=int(os.getenv("ZEABUR_RESYNC_ATTEMPTS", "3")))
    parser.add_argument("--skip-wait", action="store_true")
    parser.add_argument("--skip-health-version-wait", action="store_true")
    parser.add_argument("--skip-sync", action="store_true")
    parser.add_argument("--skip-verify", action="store_true")
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--sync-extra-args", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    args.local_wiki = args.local_wiki.expanduser().resolve()
    expected_version = args.expected_version or expected_version_from_app(repo_root)
    min_wiki_files = args.min_wiki_files or sum(1 for path in args.local_wiki.rglob("*.md") if path.is_file())
    print(f"expected_app_version={expected_version or '(not enforced)'}")
    print(f"min_llm_wiki_files={min_wiki_files}")
    if not args.skip_wait:
        wait_for_running(args.service_id, args.env_id, args.timeout, args.interval)
    if not args.skip_health_version_wait:
        wait_for_health_version(
            args.base_url,
            expected_version,
            args.timeout,
            args.interval,
            max(1, args.health_stable_checks),
        )

    if not args.skip_sync:
        last_error: Exception | None = None
        for attempt in range(1, max(1, args.resync_attempts) + 1):
            print(f"sync_attempt={attempt}")
            run_stream(sync_command(repo_root, args))
            if args.skip_verify:
                break
            try:
                wait_for_wiki_loaded(
                    args.base_url,
                    expected_version,
                    min_wiki_files,
                    args.verify_timeout,
                    args.interval,
                )
                last_error = None
                break
            except TimeoutError as exc:
                last_error = exc
                print(f"sync_verify_failed={exc}")
        if last_error:
            raise last_error

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

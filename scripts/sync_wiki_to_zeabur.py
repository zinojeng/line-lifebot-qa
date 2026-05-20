#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import shlex
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_SERVICE_ID = "6a0c6dcf40a883532f331aa2"
DEFAULT_ENV_ID = "6a0c6dcef3b70f2a79fbd6f2"
DEFAULT_LOCAL_WIKI = Path("/Users/ander/Documents/hermes-agent/wiki/ada-kdigo-diabetes-wiki")
DEFAULT_REMOTE_WIKI = "/app/data/wiki/ada-kdigo-diabetes-wiki"
DEFAULT_RELOAD_URL = "https://linebotqa.zeabur.app/debug/knowledge/reload"
DEFAULT_HEALTH_URL = "https://linebotqa.zeabur.app/"


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("CI", "1")
    proc = subprocess.run(cmd, text=True, capture_output=True, env=env, check=False)
    if check and proc.returncode != 0:
        raise RuntimeError(
            "command failed: "
            + " ".join(shlex.quote(part) for part in cmd)
            + f"\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return proc


def zeabur_exec(service_id: str, env_id: str, remote_cmd: str) -> str:
    proc = run(
        [
            "npx",
            "zeabur",
            "--interactive=false",
            "service",
            "exec",
            "--id",
            service_id,
            "--env-id",
            env_id,
            "--",
            "sh",
            "-lc",
            remote_cmd,
        ]
    )
    return (proc.stdout + proc.stderr).strip()


def make_archive(local_wiki: Path) -> bytes:
    if not local_wiki.exists():
        raise FileNotFoundError(local_wiki)
    with tempfile.NamedTemporaryFile(suffix=".tar.gz") as tmp:
        with tarfile.open(tmp.name, "w:gz", dereference=False) as tar:
            for path in sorted(local_wiki.rglob("*")):
                rel = path.relative_to(local_wiki.parent)
                if any(part in {".git", "__pycache__"} for part in rel.parts):
                    continue
                if path.name in {".DS_Store"} or path.name.startswith("._"):
                    continue
                tar.add(path, arcname=rel.as_posix(), recursive=False)
        tmp.seek(0)
        return tmp.read()


def post_json(url: str, token: str = "", timeout_seconds: int = 240) -> dict[str, object]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["x-debug-token"] = token
    request = urllib.request.Request(url, data=b"{}", headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        raw = response.read().decode("utf-8", errors="replace")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {"raw": raw}
    return payload if isinstance(payload, dict) else {"raw": payload}


def get_json(url: str) -> dict[str, object]:
    with urllib.request.urlopen(url, timeout=30) as response:
        raw = response.read().decode("utf-8", errors="replace")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {"raw": raw}
    return payload if isinstance(payload, dict) else {"raw": payload}


def sync_wiki(
    local_wiki: Path,
    remote_wiki: str,
    service_id: str,
    env_id: str,
    *,
    chunk_chars: int,
    reload_url: str,
    health_url: str,
    debug_token: str,
    reload_timeout: int,
    reload_after: bool,
) -> None:
    archive = make_archive(local_wiki)
    encoded = base64.b64encode(archive).decode("ascii")
    remote_parent = str(Path(remote_wiki).parent)
    remote_tmp_b64 = f"/tmp/{local_wiki.name}.tar.gz.b64"
    remote_tmp_tgz = f"/tmp/{local_wiki.name}.tar.gz"

    local_md_count = sum(1 for path in local_wiki.rglob("*.md") if path.is_file())
    print(f"local_wiki={local_wiki}")
    print(f"local_markdown_files={local_md_count}")
    print(f"archive_bytes={len(archive)} base64_chars={len(encoded)} chunks={(len(encoded) + chunk_chars - 1) // chunk_chars}")

    zeabur_exec(service_id, env_id, f"rm -f {shlex.quote(remote_tmp_b64)} {shlex.quote(remote_tmp_tgz)}")
    for index in range(0, len(encoded), chunk_chars):
        chunk = encoded[index : index + chunk_chars]
        zeabur_exec(service_id, env_id, f"printf %s {shlex.quote(chunk)} >> {shlex.quote(remote_tmp_b64)}")
        print(f"uploaded_chunk={(index // chunk_chars) + 1}")

    preserve_dirs = "inbox/query-candidates inbox/retrieval-failures inbox/answer-improvements"
    remote_cmd = " && ".join(
        [
            "PRESERVE_DIR=/tmp/ada-kdigo-wiki-preserve-$$",
            "rm -rf \"$PRESERVE_DIR\" && mkdir -p \"$PRESERVE_DIR\"",
            (
                f"for d in {preserve_dirs}; do "
                f"if [ -d {shlex.quote(remote_wiki)}/$d ]; then "
                "mkdir -p \"$PRESERVE_DIR/$(dirname \"$d\")\"; "
                f"cp -a {shlex.quote(remote_wiki)}/$d \"$PRESERVE_DIR/$d\"; "
                "fi; done"
            ),
            f"mkdir -p {shlex.quote(remote_parent)}",
            f"base64 -d {shlex.quote(remote_tmp_b64)} > {shlex.quote(remote_tmp_tgz)}",
            f"rm -rf {shlex.quote(remote_wiki)}",
            f"tar -xzf {shlex.quote(remote_tmp_tgz)} -C {shlex.quote(remote_parent)}",
            (
                f"for d in {preserve_dirs}; do "
                "if [ -d \"$PRESERVE_DIR/$d\" ]; then "
                f"mkdir -p {shlex.quote(remote_wiki)}/$d; "
                f"cp -a \"$PRESERVE_DIR/$d/.\" {shlex.quote(remote_wiki)}/$d/; "
                "fi; done"
            ),
            f"find {shlex.quote(remote_wiki)} \\( -name '._*' -o -name '.DS_Store' \\) -delete",
            "rm -rf \"$PRESERVE_DIR\"",
            f"rm -f {shlex.quote(remote_tmp_b64)} {shlex.quote(remote_tmp_tgz)}",
            f"printf 'remote_markdown_files=' && find {shlex.quote(remote_wiki)} -name '*.md' | wc -l",
        ]
    )
    print(zeabur_exec(service_id, env_id, remote_cmd))

    if reload_after:
        try:
            payload = post_json(reload_url, debug_token, reload_timeout)
            print("reload=" + json.dumps(payload, ensure_ascii=False)[:2000])
        except Exception as exc:
            print(f"reload_failed={exc}")
        try:
            payload = get_json(health_url)
            print("health=" + json.dumps(payload, ensure_ascii=False)[:2000])
        except Exception as exc:
            print(f"health_failed={exc}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync local ADA-KDIGO LLM Wiki into the Zeabur container.")
    parser.add_argument("--local-wiki", type=Path, default=Path(os.getenv("LOCAL_WIKI_PATH", DEFAULT_LOCAL_WIKI)))
    parser.add_argument("--remote-wiki", default=os.getenv("REMOTE_WIKI_PATH", DEFAULT_REMOTE_WIKI))
    parser.add_argument("--service-id", default=os.getenv("ZEABUR_SERVICE_ID", DEFAULT_SERVICE_ID))
    parser.add_argument("--env-id", default=os.getenv("ZEABUR_ENV_ID", DEFAULT_ENV_ID))
    parser.add_argument("--chunk-chars", type=int, default=int(os.getenv("ZEABUR_SYNC_CHUNK_CHARS", "18000")))
    parser.add_argument("--reload-url", default=os.getenv("LINEBOT_RELOAD_URL", DEFAULT_RELOAD_URL))
    parser.add_argument("--health-url", default=os.getenv("LINEBOT_HEALTH_URL", DEFAULT_HEALTH_URL))
    parser.add_argument("--debug-token", default=os.getenv("LINE_DEBUG_TOKEN", ""))
    parser.add_argument("--reload-timeout", type=int, default=int(os.getenv("LINEBOT_RELOAD_TIMEOUT", "240")))
    parser.add_argument("--reload", action="store_true", help="Call /debug/knowledge/reload after syncing.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sync_wiki(
        args.local_wiki.expanduser().resolve(),
        args.remote_wiki,
        args.service_id,
        args.env_id,
        chunk_chars=args.chunk_chars,
        reload_url=args.reload_url,
        health_url=args.health_url,
        debug_token=args.debug_token,
        reload_timeout=args.reload_timeout,
        reload_after=args.reload,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

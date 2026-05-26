#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import os
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


DEFAULT_SERVICE_ID = "6a0c6dcf40a883532f331aa2"
DEFAULT_ENV_ID = "6a0c6dcef3b70f2a79fbd6f2"
DEFAULT_REMOTE_WIKI = "/app/data/wiki/ada-kdigo-diabetes-wiki"
DEFAULT_LOCAL_WIKI = Path("/Users/ander/Documents/hermes-agent/wiki/ada-kdigo-diabetes-wiki")
INBOX_DIRS = (
    "inbox/query-candidates",
    "inbox/retrieval-failures",
    "inbox/answer-improvements",
    "inbox/research-requests",
)


def run(cmd: list[str], *, check: bool = True, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        env={**os.environ, "CI": "1"},
        check=False,
        timeout=timeout,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            "command failed: "
            + " ".join(shlex.quote(part) for part in cmd)
            + f"\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return proc


def zeabur_exec(service_id: str, env_id: str, remote_cmd: str, timeout: int) -> str:
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
        ],
        timeout=timeout,
    )
    return (proc.stdout + proc.stderr).strip()


def archive_from_remote(service_id: str, env_id: str, remote_wiki: str, timeout: int) -> bytes:
    dirs = " ".join(shlex.quote(item) for item in INBOX_DIRS)
    marker_start = "__LIFEBOT_INBOX_ARCHIVE_BEGIN__"
    marker_end = "__LIFEBOT_INBOX_ARCHIVE_END__"
    remote_cmd = (
        f"printf '{marker_start}\\n'; "
        f"if [ -d {shlex.quote(remote_wiki)} ]; then "
        f"cd {shlex.quote(remote_wiki)} && tar -czf - {dirs} 2>/dev/null | base64; "
        "fi; "
        f"printf '\\n{marker_end}\\n'"
    )
    output = zeabur_exec(service_id, env_id, remote_cmd, timeout)
    match = re.search(rf"{marker_start}\s*(.*?)\s*{marker_end}", output, flags=re.S)
    if not match:
        raise RuntimeError(f"could not find inbox archive markers in Zeabur exec output:\n{output[:2000]}")
    encoded = re.sub(r"[^A-Za-z0-9+/=]", "", match.group(1))
    if not encoded:
        return b""
    return base64.b64decode(encoded)


def extract_archive(archive: bytes, local_wiki: Path) -> int:
    if not archive:
        return 0
    local_wiki.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".tar.gz") as tmp:
        tmp.write(archive)
        tmp.flush()
        with tarfile.open(tmp.name, "r:gz") as tar:
            members = [member for member in tar.getmembers() if member.name.startswith("inbox/")]
            tar.extractall(local_wiki, members=members)
    return sum(1 for path in (local_wiki / "inbox").rglob("*.md") if path.is_file())


def run_compilers(repo_root: Path) -> None:
    for script in ("compile_retrieval_failures.py", "compile_answer_improvements.py", "weekly_wiki_health_report.py"):
        run([sys.executable, str(repo_root / "scripts" / script)], check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pull Zeabur LLM Wiki inbox records back to the local Obsidian wiki.")
    parser.add_argument("--service-id", default=os.getenv("ZEABUR_SERVICE_ID", DEFAULT_SERVICE_ID))
    parser.add_argument("--env-id", default=os.getenv("ZEABUR_ENV_ID", DEFAULT_ENV_ID))
    parser.add_argument("--remote-wiki", default=os.getenv("REMOTE_WIKI_PATH", DEFAULT_REMOTE_WIKI))
    parser.add_argument("--local-wiki", type=Path, default=Path(os.getenv("LOCAL_WIKI_PATH", DEFAULT_LOCAL_WIKI)))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("ZEABUR_INBOX_PULL_TIMEOUT", "60")))
    parser.add_argument("--skip-compile", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    local_wiki = args.local_wiki.expanduser().resolve()
    archive = archive_from_remote(args.service_id, args.env_id, args.remote_wiki, args.timeout)
    file_count = extract_archive(archive, local_wiki)
    print(f"local_wiki={local_wiki}")
    print(f"pulled_inbox_markdown_files={file_count}")
    if not args.skip_compile:
        run_compilers(repo_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

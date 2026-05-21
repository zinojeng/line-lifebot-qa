#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WIKI = Path("/Users/ander/Documents/hermes-agent/wiki/ada-kdigo-diabetes-wiki")


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    print("$ " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=REPO_ROOT, text=True, check=False)
    if check and proc.returncode != 0:
        raise SystemExit(proc.returncode)
    return proc


def py(script: str, *args: str) -> list[str]:
    return [sys.executable, str(REPO_ROOT / "scripts" / script), *args]


def compile_all(wiki: Path) -> None:
    run(py("build_wiki_index.py", "--wiki", str(wiki)))
    run(py("wiki_fts_search.py", "--wiki", str(wiki), "--rebuild"))
    run(py("generate_synthetic_qa.py", "--wiki", str(wiki)))
    run(py("source_freshness_watch.py", "--wiki", str(wiki), "--no-network"))


def health_check(wiki: Path, audit_request_limit: int) -> None:
    run(
        py(
            "wiki_self_improvement_audit.py",
            "--wiki",
            str(wiki),
            "--write-requests",
            "--request-limit",
            str(audit_request_limit),
        )
    )
    run(py("weekly_wiki_health_report.py"))


def daily(wiki: Path, request_limit: int) -> None:
    compile_all(wiki)
    health_check(wiki, request_limit)
    run(
        py(
            "hermes_daily_wiki_self_improvement.py",
            "--request-limit",
            str(request_limit),
            "--audit-request-limit",
            str(request_limit),
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Unified operations entrypoint for the ADA-KDIGO LLM Wiki.")
    parser.add_argument(
        "command",
        choices=[
            "compile",
            "health-check",
            "daily",
            "generate-qa",
            "freshness",
            "fts-build",
            "fts-search",
            "search",
            "regression",
        ],
    )
    parser.add_argument("query", nargs="?", default="")
    parser.add_argument("--wiki", type=Path, default=DEFAULT_WIKI)
    parser.add_argument("--request-limit", type=int, default=2)
    parser.add_argument(
        "--audit-request-limit",
        type=int,
        default=4,
        help="Maximum research requests to open during standalone health-check; daily uses --request-limit for both safety caps.",
    )
    parser.add_argument("--base-url", default="https://linebotqa.zeabur.app")
    parser.add_argument("--include-generated", action="store_true")
    args = parser.parse_args()
    if args.request_limit < 1 or args.audit_request_limit < 1:
        parser.error("--request-limit and --audit-request-limit must be >= 1")

    wiki = args.wiki.expanduser().resolve()
    if args.command == "compile":
        compile_all(wiki)
    elif args.command == "health-check":
        health_check(wiki, args.audit_request_limit)
    elif args.command == "daily":
        daily(wiki, args.request_limit)
    elif args.command == "generate-qa":
        run(py("generate_synthetic_qa.py", "--wiki", str(wiki)))
    elif args.command == "freshness":
        run(py("source_freshness_watch.py", "--wiki", str(wiki), "--no-network"))
    elif args.command == "fts-build":
        run(py("wiki_fts_search.py", "--wiki", str(wiki), "--rebuild"))
    elif args.command == "fts-search":
        if not args.query:
            parser.error("fts-search requires query")
        run(py("wiki_fts_search.py", args.query, "--wiki", str(wiki)))
    elif args.command == "search":
        if not args.query:
            parser.error("search requires query")
        run(py("wiki_search.py", args.query, "--wiki", str(wiki)))
    elif args.command == "regression":
        cmd = py("answer_quality_regression_tests.py", "--base-url", args.base_url)
        if args.include_generated:
            cmd.append("--include-generated")
        run(cmd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

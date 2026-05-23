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


def compile_all(wiki: Path, allow_missing_section12: bool = False) -> None:
    run(py("build_wiki_index.py", "--wiki", str(wiki)))
    contract = run(py("check_required_wiki_pages.py", "--wiki", str(wiki)), check=False)
    if contract.returncode != 0:
        print("WARNING: required wiki page contract check failed; continuing compile so unrelated indexes still rebuild.")
    run(py("generate_synthetic_qa.py", "--wiki", str(wiki)))
    run(py("source_freshness_watch.py", "--wiki", str(wiki), "--no-network"))
    # Generated reports change Markdown content; refresh registries and FTS after
    # those writes so local search never serves the previous report versions.
    run(py("build_wiki_index.py", "--wiki", str(wiki)))
    run(py("wiki_link_strength.py", "--wiki", str(wiki)))
    # Link-strength writes a report Markdown page; refresh registries again so
    # report summaries and search chunks describe the current graph snapshot.
    run(py("build_wiki_index.py", "--wiki", str(wiki)))
    run(py("wiki_fts_search.py", "--wiki", str(wiki), "--rebuild"))
    if contract.returncode != 0:
        if allow_missing_section12:
            print("WARNING: Section 12 contract failed, but --allow-missing-section12 was set; returning success.", file=sys.stderr)
            return
        print("ERROR: required wiki page contract check failed; compile artifacts were rebuilt but this wiki is incomplete.", file=sys.stderr)
        raise SystemExit(contract.returncode)


def refresh_registries(wiki: Path) -> None:
    """Refresh generated search artifacts after commands that rewrite Markdown."""
    run(py("build_wiki_index.py", "--wiki", str(wiki)))
    run(py("wiki_fts_search.py", "--wiki", str(wiki), "--rebuild"))


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


def daily(wiki: Path, request_limit: int, allow_missing_section12: bool = False) -> None:
    compile_all(wiki, allow_missing_section12)
    health_check(wiki, request_limit)
    run(
        py(
            "hermes_daily_wiki_self_improvement.py",
            "--wiki",
            str(wiki),
            "--request-limit",
            str(request_limit),
            "--audit-request-limit",
            str(request_limit),
            "--weak-link-limit",
            str(min(2, request_limit)),
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
            "md-audit",
            "md-normalize",
            "fts-build",
            "fts-search",
            "search",
            "link-strength",
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
    parser.add_argument("--max-files", type=int, default=3)
    parser.add_argument(
        "--allow-missing-section12",
        action="store_true",
        help="Transitional mode for non-ADA wiki vaults: rebuild artifacts even if the ADA Section 12 routing contract is missing.",
    )
    args = parser.parse_args()
    if args.request_limit < 1 or args.audit_request_limit < 1:
        parser.error("--request-limit and --audit-request-limit must be >= 1")

    wiki = args.wiki.expanduser().resolve()
    if args.command == "compile":
        compile_all(wiki, args.allow_missing_section12)
    elif args.command == "health-check":
        health_check(wiki, args.audit_request_limit)
    elif args.command == "daily":
        daily(wiki, args.request_limit, args.allow_missing_section12)
    elif args.command == "generate-qa":
        run(py("generate_synthetic_qa.py", "--wiki", str(wiki)))
    elif args.command == "freshness":
        run(py("source_freshness_watch.py", "--wiki", str(wiki), "--no-network"))
    elif args.command == "md-audit":
        run(py("normalize_wiki_markdown.py", "--wiki", str(wiki), "--write-report"))
        refresh_registries(wiki)
    elif args.command == "md-normalize":
        run(
            py(
                "normalize_wiki_markdown.py",
                "--wiki",
                str(wiki),
                "--apply",
                "--max-files",
                str(args.max_files),
                "--write-report",
            )
        )
        refresh_registries(wiki)
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
    elif args.command == "link-strength":
        run(py("wiki_link_strength.py", "--wiki", str(wiki)))
    elif args.command == "regression":
        cmd = py("answer_quality_regression_tests.py", "--base-url", args.base_url)
        if args.include_generated:
            cmd.append("--include-generated")
        run(cmd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

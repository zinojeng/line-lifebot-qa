#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path("/Users/ander/Documents/hermes-agent/line-lifebot-qa")
WIKI_ROOT = Path("/Users/ander/Documents/hermes-agent/wiki/ada-kdigo-diabetes-wiki")


def run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, cwd=REPO_ROOT, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        return (
            f"$ {' '.join(cmd)}\n"
            f"exit={proc.returncode}\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}\n"
        )
    return proc.stdout.strip()


def frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return ""
    match = re.match(r"^---\s*\n(.*?)\n---", text, flags=re.S)
    return match.group(1) if match else ""


def fm_value(fm: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}:\s*(.*)$", fm, flags=re.M)
    return match.group(1).strip() if match else ""


def open_research_requests(limit: int) -> list[Path]:
    request_dir = WIKI_ROOT / "inbox" / "research-requests"
    paths = []
    for path in sorted(request_dir.glob("*.md")):
        if path.name == "README.md":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        fm = frontmatter(text)
        status = fm_value(fm, "status").lower()
        if status in {"resolved", "retired", "closed", "done"}:
            continue
        paths.append(path)
    return paths[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Daily Hermes input generator: run self-audit and select 1-2 research requests."
    )
    parser.add_argument("--request-limit", type=int, default=2)
    parser.add_argument("--audit-request-limit", type=int, default=4)
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    audit_out = run(
        [
            "python3",
            "scripts/wiki_self_improvement_audit.py",
            "--write-requests",
            "--request-limit",
            str(args.audit_request_limit),
        ]
    )
    synthetic_out = run(["python3", "scripts/generate_synthetic_qa.py"])
    freshness_out = run(["python3", "scripts/source_freshness_watch.py", "--no-network"])
    health_out = run(["python3", "scripts/weekly_wiki_health_report.py"])
    selected = open_research_requests(args.request_limit)

    lines = [
        "# Daily ADA-KDIGO LLM Wiki Self-Improvement Input",
        "",
        f"Generated: {stamp}",
        "",
        "## Commands Run",
        "",
        f"- self audit: {audit_out or 'ok'}",
        f"- synthetic QA generation: {synthetic_out or 'ok'}",
        f"- source freshness watch: {freshness_out or 'ok'}",
        f"- health report: {health_out or 'ok'}",
        "",
        "## Selected Open Research Requests",
        "",
    ]
    if not selected:
        lines.append("- None")
    for idx, path in enumerate(selected, 1):
        rel = path.relative_to(WIKI_ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        body = text.split("---", 2)[-1].strip() if text.startswith("---") else text
        lines.extend(
            [
                f"### Request {idx}: {rel}",
                "",
                body[:3500],
                "",
            ]
        )

    lines.extend(
        [
            "## Hermes Task",
            "",
            "Process only the selected 1-2 requests today.",
            "",
            "Required workflow:",
            "",
            "1. Read WIKI_PATH/HERMES.md, SCHEMA.md, index.md, _meta/topic-map.md, _meta/aliases.md, and reports/wiki-self-improvement-audit.md.",
            "2. For each selected request, search existing wiki pages first with the local wiki-search pattern; avoid duplicate pages.",
            "3. Read reports/synthetic-qa-candidates.md and reports/source-freshness-watch.md for regression and source-change signals.",
            "4. Verify clinical facts against raw ADA/KDIGO Markdown before changing thresholds, grades, drug indications, diagnosis cutoffs, or contraindications.",
            "5. Safe autonomous edits are allowed: aliases, topic-map routes, typed-relationship edges, claim-registry routing, smoke-test suggestions, short draft concept pages with clear sources, and status updates on processed research-request files.",
            "6. If raw-source verification is incomplete, create or update a draft/proposal and leave the request status open or needs-source.",
            "7. Do not process more than the selected requests. Do not mass-edit the wiki.",
            "8. Update log.md with a concise entry if any file is edited.",
            "9. In the final report, list files read, files edited, requests processed, unresolved evidence gaps, and next queued requests.",
        ]
    )
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

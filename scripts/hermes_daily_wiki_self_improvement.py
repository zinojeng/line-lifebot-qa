#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
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


def open_research_requests(root: Path, limit: int) -> list[Path]:
    request_dir = root / "inbox" / "research-requests"
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


def selected_weak_link_tasks(root: Path, limit: int) -> list[dict[str, object]]:
    path = root / "_meta" / "link-strength.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    tasks = []
    for row in payload.get("weak_nodes", []):
        if not isinstance(row, dict):
            continue
        page = str(row.get("path", ""))
        if not page or page.startswith(("raw/", "inbox/")):
            continue
        tasks.append(
            {
                "path": page,
                "score": row.get("score"),
                "aliases": row.get("aliases"),
                "wikilinks": row.get("wikilinks"),
                "safe_action": "Add inbound related/MOC/typed-relationship links from already source-grounded neighboring pages; do not create new clinical claims.",
            }
        )
        if len(tasks) >= limit:
            break
    return tasks


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Daily Hermes input generator: run self-audit and select 1-2 research requests."
    )
    parser.add_argument("--wiki", type=Path, default=WIKI_ROOT)
    parser.add_argument("--request-limit", type=int, default=2)
    parser.add_argument("--audit-request-limit", type=int, default=4)
    parser.add_argument("--weak-link-limit", type=int, default=2)
    args = parser.parse_args()
    wiki_root = args.wiki.expanduser().resolve()

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    index_out = run(["python3", "scripts/build_wiki_index.py", "--wiki", str(wiki_root)])
    link_strength_out = run(["python3", "scripts/wiki_link_strength.py", "--wiki", str(wiki_root)])
    post_link_index_out = run(["python3", "scripts/build_wiki_index.py", "--wiki", str(wiki_root)])
    fts_out = run(["python3", "scripts/wiki_fts_search.py", "--wiki", str(wiki_root), "--rebuild"])
    audit_out = run(
        [
            "python3",
            "scripts/wiki_self_improvement_audit.py",
            "--wiki",
            str(wiki_root),
            "--write-requests",
            "--request-limit",
            str(args.audit_request_limit),
        ]
    )
    synthetic_out = run(["python3", "scripts/generate_synthetic_qa.py", "--wiki", str(wiki_root)])
    freshness_out = run(["python3", "scripts/source_freshness_watch.py", "--wiki", str(wiki_root), "--no-network"])
    health_out = run(["python3", "scripts/weekly_wiki_health_report.py"])
    selected = open_research_requests(wiki_root, args.request_limit)
    weak_link_tasks = selected_weak_link_tasks(wiki_root, args.weak_link_limit)

    lines = [
        "# Daily ADA-KDIGO LLM Wiki Self-Improvement Input",
        "",
        f"Generated: {stamp}",
        "",
        "## Commands Run",
        "",
        f"- machine-readable wiki index: {index_out or 'ok'}",
        f"- link-strength graph scoring: {link_strength_out or 'ok'}",
        f"- post-link-strength registry refresh: {post_link_index_out or 'ok'}",
        f"- SQLite FTS search index: {fts_out or 'ok'}",
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
        rel = path.relative_to(wiki_root).as_posix()
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
    lines.extend(["", "## Selected Weak-Link Tasks", ""])
    if not weak_link_tasks:
        lines.append("- None")
    for idx, task in enumerate(weak_link_tasks, 1):
        lines.extend(
            [
                f"### Weak-Link Task {idx}: {task['path']}",
                "",
                f"- Current score: {task['score']}",
                f"- Aliases: {task['aliases']}",
                f"- Wikilinks: {task['wikilinks']}",
                f"- Safe action: {task['safe_action']}",
                "",
            ]
        )

    lines.extend(
        [
            "## Hermes Task",
            "",
            "Process only the selected 1-2 research requests and 1-2 weak-link tasks today.",
            "",
            "Required workflow:",
            "",
            "1. Read WIKI_PATH/HERMES.md, SCHEMA.md, index.md, _meta/INDEX.json, _meta/page-registry.json, _meta/claim-registry.json, _meta/topic-map.md, _meta/aliases.md, and reports/wiki-self-improvement-audit.md.",
            "2. For each selected request, search existing wiki pages first with the local wiki-search pattern; avoid duplicate pages.",
            "3. Use scripts/wiki_fts_search.py for QMD-like local search when exact title/alias search is not enough.",
            "4. Read reports/link-strength-report.md, reports/synthetic-qa-candidates.md, and reports/source-freshness-watch.md for graph, regression, and source-change signals.",
            "5. Verify clinical facts against raw ADA/KDIGO Markdown before changing thresholds, grades, drug indications, diagnosis cutoffs, or contraindications.",
            "6. Safe autonomous edits are allowed: inbound related links, MOC routes, typed-relationship edges, aliases, claim-registry routing, evidence-ledger entries, smoke-test suggestions, short draft concept pages with clear sources, and status updates on processed research-request files.",
            "7. If raw-source verification is incomplete, create or update a draft/proposal and leave the request status open or needs-source.",
            "8. Do not process more than the selected requests or weak-link tasks. Do not mass-edit the wiki.",
            "9. Update log.md with a concise entry if any file is edited.",
            "10. In the final report, list files read, files edited, requests processed, unresolved evidence gaps, and next queued requests.",
        ]
    )
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

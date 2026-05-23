#!/usr/bin/env python3
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path


DEFAULT_WIKI = Path("/Users/ander/Documents/hermes-agent/wiki/ada-kdigo-diabetes-wiki")


def section(text: str, heading: str) -> str:
    pattern = rf"^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, text, flags=re.M | re.S)
    return match.group(1).strip() if match else ""


def bullet_values(text: str, label: str) -> str:
    match = re.search(rf"^- {re.escape(label)}:\s*(.*)$", text, flags=re.M)
    return match.group(1).strip() if match else ""


def classify_route(text: str) -> str:
    route_section = section(text, "Matched Route Candidates")
    routes = re.findall(r"`([^`]+)`", route_section)
    if routes:
        return routes[0]
    question = section(text, "Question").lower()
    if re.search(r"sglt|排糖藥|egfr.*20|腎功能.*20", question):
        return "drugs/sglt2i-egfr-under-20-not-on-dialysis"
    if re.search(r"glp|洗腎|透析|dialysis", question):
        return "drugs/glp1-based-therapy-on-dialysis"
    if re.search(r"cgm|連續血糖|血糖機|time in range", question):
        return "concepts/diabetes-technology-cgm-aid"
    if re.search(r"uacr|albuminuria|白蛋白尿|尿蛋白|ckd|腎", question):
        return "concepts/diabetes-ckd-risk-stratification"
    return "unrouted"


def main() -> int:
    root = DEFAULT_WIKI
    failure_dir = root / "inbox" / "retrieval-failures"
    report_dir = root / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(path for path in failure_dir.glob("*.md") if path.name != "README.md") if failure_dir.exists() else []

    stage_counts = Counter()
    type_counts = Counter()
    route_groups: dict[str, list[Path]] = defaultdict(list)
    suggested = Counter()

    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        stage_counts[bullet_values(text, "stage") or "unknown"] += 1
        for value in [item.strip() for item in bullet_values(text, "failure_types").split(",") if item.strip()]:
            type_counts[value] += 1
        route_groups[classify_route(text)].append(path)
        for line in section(text, "Suggested Low-Risk Fixes").splitlines():
            line = line.strip("- ").strip()
            if line:
                suggested[line] += 1

    out = report_dir / "retrieval-failure-analysis.md"
    today = date.today().isoformat()
    lines = [
        "---",
        "title: Retrieval Failure Analysis",
        "summary: Generated report grouping open retrieval-failure records by failure stage, failure type, route group, and suggested low-risk fixes.",
        "type: report",
        f"created: {today}",
        f"updated: {today}",
        "tags: [llm-wiki, retrieval-failure, line-qa, report]",
        "sources:",
        "  - inbox/retrieval-failures/README.md",
        "evidence_level: local-practice",
        "clinical_use: workflow",
        "confidence: medium",
        f"last_verified: {today}",
        "status: draft",
        "obsidian_type: report",
        "aliases:",
        "  - retrieval failure analysis",
        "entities:",
        "  - LINE QA",
        "  - Hermes Agent",
        "related:",
        "  - inbox/retrieval-failures/README",
        "  - reports/weekly-wiki-health",
        "  - reports/answer-improvement-analysis",
        "owner_agent: hermes",
        "write_policy: hermes-maintained",
        "---",
        "",
        "# Retrieval Failure Analysis",
        "",
        f"Generated: {today}",
        "",
        "## Summary",
        "",
        f"- Open failure records: {len(files)}",
        f"- Routed groups: {len(route_groups)}",
        "",
        "## Failure Stages",
        "",
    ]
    if stage_counts:
        lines.extend(f"- {stage}: {count}" for stage, count in stage_counts.most_common())
    else:
        lines.append("- None")
    lines.extend(["", "## Failure Types", ""])
    if type_counts:
        lines.extend(f"- {kind}: {count}" for kind, count in type_counts.most_common())
    else:
        lines.append("- None")
    lines.extend(["", "## Route Groups", ""])
    if route_groups:
        for route, paths in sorted(route_groups.items(), key=lambda item: (-len(item[1]), item[0])):
            lines.append(f"### {route}")
            lines.append("")
            for path in paths[:12]:
                lines.append(f"- [[../inbox/retrieval-failures/{path.stem}]]")
            if len(paths) > 12:
                lines.append(f"- ... {len(paths) - 12} more")
            lines.append("")
    else:
        lines.append("- None")
        lines.append("")
    lines.extend(["## Repeated Suggested Fixes", ""])
    if suggested:
        lines.extend(f"- {fix} ({count})" for fix, count in suggested.most_common(30))
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Safe Compiler Policy",
            "",
            "Automatically allowed:",
            "",
            "- add aliases/entities after canonical route review;",
            "- add topic-map or MOC route links;",
            "- create query page drafts after source verification;",
            "- create research requests for true source gaps.",
            "",
            "Not automatically allowed:",
            "",
            "- change clinical thresholds;",
            "- change recommendation grades;",
            "- promote draft guidance to final;",
            "- add unsourced clinical claims.",
        ]
    )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

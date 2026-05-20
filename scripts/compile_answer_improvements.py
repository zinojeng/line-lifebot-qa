#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path


DEFAULT_WIKI = Path("/Users/ander/Documents/hermes-agent/wiki/ada-kdigo-diabetes-wiki")


def section(text: str, heading: str) -> str:
    pattern = rf"^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, text, flags=re.M | re.S)
    return match.group(1).strip() if match else ""


def bullet_value(text: str, label: str) -> str:
    match = re.search(rf"^- {re.escape(label)}:\s*(.*)$", text, flags=re.M)
    return match.group(1).strip() if match else ""


def review_json(text: str) -> dict[str, object]:
    review = section(text, "Answer Improvement Review") or section(text, "OpenAI Mini Review")
    match = re.search(r"```json\s*(.*?)\s*```", review, flags=re.S)
    raw = match.group(1) if match else review
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def list_values(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def classify_topic(text: str) -> str:
    question = section(text, "Question").lower()
    if re.search(r"骨|骨鬆|骨質疏鬆|osteoporosis|fracture|bone", question):
        return "bone-health"
    if re.search(r"sglt|排糖藥|egfr.*20|腎功能.*20", question):
        return "sglt2i-egfr"
    if re.search(r"glp|洗腎|透析|dialysis", question):
        return "glp1-dialysis"
    if re.search(r"cgm|連續血糖|time in range|tir", question):
        return "cgm-aid"
    if re.search(r"ckd|腎|uacr|albuminuria|尿蛋白", question):
        return "diabetes-ckd"
    return "unrouted"


def main() -> int:
    root = DEFAULT_WIKI
    improvement_dir = root / "inbox" / "answer-improvements"
    report_dir = root / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(path for path in improvement_dir.glob("*.md") if path.name != "README.md") if improvement_dir.exists() else []

    topics: dict[str, list[Path]] = defaultdict(list)
    public_wording = Counter()
    missing_facets = Counter()
    retrieval_issues = Counter()
    safe_actions = Counter()
    human_review = []
    quality_scores = []

    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        topics[classify_topic(text)].append(path)
        review = review_json(text)
        if not review:
            retrieval_issues["review_json_missing_or_invalid"] += 1
            continue
        if review.get("requires_human_or_clinical_review"):
            human_review.append(path)
        try:
            quality_scores.append(float(review.get("quality_score", 0)))
        except (TypeError, ValueError):
            pass
        for value in list_values(review.get("public_wording_issues")):
            public_wording[value] += 1
        for value in list_values(review.get("missing_evidence_facets")):
            missing_facets[value] += 1
        for value in list_values(review.get("retrieval_route_issues")):
            retrieval_issues[value] += 1
        for value in list_values(review.get("safe_auto_actions")):
            safe_actions[value] += 1

    out = report_dir / "answer-improvement-analysis.md"
    avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0
    lines = [
        "# Answer Improvement Analysis",
        "",
        f"Generated: {date.today().isoformat()}",
        "",
        "## Summary",
        "",
        f"- Open answer improvement records: {len(files)}",
        f"- Average quality score: {avg_quality:.2f}",
        f"- Records requiring human/source review: {len(human_review)}",
        f"- Routed topics: {len(topics)}",
        "",
        "## Topic Groups",
        "",
    ]
    if topics:
        for topic, paths in sorted(topics.items(), key=lambda item: (-len(item[1]), item[0])):
            lines.append(f"### {topic}")
            lines.append("")
            for path in paths[:12]:
                lines.append(f"- [[../inbox/answer-improvements/{path.stem}]]")
            if len(paths) > 12:
                lines.append(f"- ... {len(paths) - 12} more")
            lines.append("")
    else:
        lines.append("- None")
        lines.append("")

    buckets = [
        ("Repeated Public Wording Issues", public_wording),
        ("Repeated Missing Evidence Facets", missing_facets),
        ("Repeated Retrieval Route Issues", retrieval_issues),
        ("Repeated Safe Auto Actions", safe_actions),
    ]
    for title, counter in buckets:
        lines.extend([f"## {title}", ""])
        if counter:
            lines.extend(f"- {item} ({count})" for item, count in counter.most_common(30))
        else:
            lines.append("- None")
        lines.append("")

    lines.extend(
        [
            "## Safe Compiler Policy",
            "",
            "Automatically allowed:",
            "",
            "- add aliases/entities that point to existing canonical pages;",
            "- add topic-map or MOC links;",
            "- add smoke-test cases;",
            "- create research requests for source gaps.",
            "",
            "Not automatically allowed:",
            "",
            "- change clinical thresholds;",
            "- change recommendation grades;",
            "- change drug indications or contraindications;",
            "- promote generated clinical claims into canonical pages without source review.",
        ]
    )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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


def frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return ""
    match = re.match(r"^---\s*\n(.*?)\n---", text, flags=re.S)
    return match.group(1) if match else ""


def frontmatter_value(text: str, field: str) -> str:
    fm = frontmatter(text)
    match = re.search(rf"^{re.escape(field)}:[ \t]*(.*)$", fm, flags=re.M)
    return match.group(1).strip() if match else ""


def is_resolved_record(text: str) -> bool:
    return frontmatter_value(text, "status").strip("'\"").lower() in {"resolved", "retired", "closed", "done"}


def list_values(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def in_scope_value(value: str) -> bool:
    return "aace" not in value.lower()


def classify_topic(text: str) -> str:
    question = section(text, "Question").lower()
    if re.search(r"gdm|gestational|pregnancy|妊娠|懷孕", question) and re.search(
        r"metformin|glyburide|insulin|pharmacotherapy|medication|oral|evidence|藥|用藥|口服藥|胰島素",
        question,
    ):
        return "gdm-pharmacotherapy"
    if re.search(r"sarcopenia|smi|muscle|lean mass|handgrip|肌少症|肌肉|握力|腿沒力", question):
        return "glp1-muscle-sarcopenia"
    if re.search(r"finerenone|nsmra|非類固醇", question):
        return "diabetes-ckd"
    if re.search(r"tzd|pioglitazone|thiazolidinedione|噻唑烷二酮|胰島素增敏", question):
        return "tzd-pioglitazone"
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
    all_files = (
        sorted(path for path in improvement_dir.glob("*.md") if path.name != "README.md")
        if improvement_dir.exists()
        else []
    )
    files = [path for path in all_files if not is_resolved_record(path.read_text(encoding="utf-8", errors="ignore"))]

    topics: dict[str, list[Path]] = defaultdict(list)
    public_wording = Counter()
    missing_facets = Counter()
    retrieval_issues = Counter()
    missing_aliases = Counter()
    missing_claim_cards = Counter()
    missing_evidence_cards = Counter()
    proposed_regression_tests = Counter()
    research_requests = Counter()
    reviewer_diagnostics = Counter()
    safe_actions = Counter()
    human_review = []
    quality_scores = []
    rescaled_quality_paths = []

    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        topics[classify_topic(text)].append(path)
        review = review_json(text)
        if not review:
            reviewer_diagnostics["review_json_missing_or_invalid"] += 1
            continue
        if review.get("requires_human_or_clinical_review"):
            human_review.append(path)
        try:
            raw_score = review.get("quality_score")
            if raw_score is None:
                reviewer_diagnostics["quality_score_missing"] += 1
                score = None
            else:
                score = float(raw_score)
            if score is not None and 0 < score < 1:
                rescaled_quality_paths.append(path)
                score *= 5
            if score is not None and 0 <= score <= 5:
                quality_scores.append(score)
            elif score is not None:
                reviewer_diagnostics[f"quality_score_out_of_range:{score:g}"] += 1
        except (TypeError, ValueError):
            pass
        for value in list_values(review.get("public_wording_issues")):
            if not in_scope_value(value):
                continue
            public_wording[value] += 1
        for value in list_values(review.get("missing_evidence_facets")):
            if not in_scope_value(value):
                continue
            missing_facets[value] += 1
        for value in list_values(review.get("retrieval_route_issues")):
            if not in_scope_value(value):
                continue
            retrieval_issues[value] += 1
        for value in list_values(review.get("missing_aliases")):
            if not in_scope_value(value):
                continue
            missing_aliases[value] += 1
        for value in list_values(review.get("missing_claim_cards")):
            if not in_scope_value(value):
                continue
            missing_claim_cards[value] += 1
        for value in list_values(review.get("missing_evidence_cards")):
            if not in_scope_value(value):
                continue
            missing_evidence_cards[value] += 1
        proposed_tests = sorted({*list_values(review.get("proposed_regression_tests")), *list_values(review.get("proposed_smoke_test"))})
        for value in proposed_tests:
            if not in_scope_value(value):
                continue
            proposed_regression_tests[value] += 1
        for value in list_values(review.get("research_requests")):
            if not in_scope_value(value):
                continue
            research_requests[value] += 1
        for value in list_values(review.get("safe_auto_actions")):
            if not in_scope_value(value):
                continue
            safe_actions[value] += 1

    out = report_dir / "answer-improvement-analysis.md"
    avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0
    today = date.today().isoformat()
    lines = [
        "---",
        "title: Answer Improvement Analysis",
        "summary: Generated report grouping open LINE answer-improvement records by topic, repeated wording issues, missing evidence facets, retrieval route issues, and safe auto actions.",
        "type: report",
        f"created: {today}",
        f"updated: {today}",
        "tags: [llm-wiki, answer-improvement, line-qa, report]",
        "sources:",
        "  - inbox/answer-improvements/README.md",
        "evidence_level: local-practice",
        "clinical_use: workflow",
        "confidence: medium",
        f"last_verified: {today}",
        "status: draft",
        "obsidian_type: report",
        "aliases:",
        "  - answer improvement analysis",
        "entities:",
        "  - LINE QA",
        "  - Hermes Agent",
        "related:",
        "  - inbox/answer-improvements/README",
        "  - reports/weekly-wiki-health",
        "  - reports/retrieval-failure-analysis",
        "owner_agent: hermes",
        "write_policy: hermes-maintained",
        "---",
        "",
        "# Answer Improvement Analysis",
        "",
        f"Generated: {today}",
        "",
        "## Summary",
        "",
        f"- Open answer improvement records: {len(files)}",
        f"- Resolved answer improvement records excluded: {len(all_files) - len(files)}",
        f"- Average quality score: {avg_quality:.2f}",
        f"- Quality scores normalized from 0-1 reviewer scale to 0-5: {len(rescaled_quality_paths)}",
        "- Quality score policy: values in (0, 1) are treated as normalized reviewer scores; missing, exactly 1.0, or out-of-range scores are not auto-rescaled.",
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
        ("Repeated Missing Aliases", missing_aliases),
        ("Repeated Missing Claim Cards", missing_claim_cards),
        ("Repeated Missing Evidence Cards", missing_evidence_cards),
        ("Repeated Proposed Regression Tests", proposed_regression_tests),
        ("Repeated Research Requests", research_requests),
        ("Reviewer Diagnostics", reviewer_diagnostics),
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

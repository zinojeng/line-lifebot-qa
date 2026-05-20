#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path


DEFAULT_WIKI = Path("/Users/ander/Documents/hermes-agent/wiki/ada-kdigo-diabetes-wiki")


@dataclass(frozen=True)
class SyntheticCase:
    name: str
    query: str
    source_page: str
    expected_terms: tuple[str, ...]
    expected_mode: str = "fast_path"
    priority: str = "medium"


def split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---"):
        return "", text
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, flags=re.S)
    if not match:
        return "", text
    return match.group(1), text[match.end() :]


def field(frontmatter: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}:\s*(.*)$", frontmatter, flags=re.M)
    return match.group(1).strip() if match else ""


def list_field(frontmatter: str, key: str) -> list[str]:
    inline = field(frontmatter, key)
    values: list[str] = []
    if inline.startswith("[") and inline.endswith("]"):
        values.extend(part.strip().strip("'\"") for part in inline[1:-1].split(",") if part.strip())
    block = re.search(rf"^{re.escape(key)}:\s*\n((?:\s+- .+\n?)+)", frontmatter, flags=re.M)
    if block:
        values.extend(line.split("-", 1)[1].strip().strip("'\"") for line in block.group(1).splitlines() if "-" in line)
    return [value for value in values if value]


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80] or "synthetic-case"


def page_to_case(root: Path, path: Path) -> SyntheticCase | None:
    rel = path.relative_to(root).as_posix()
    if rel.startswith(("raw/", "reports/", "inbox/", "docs/", "_meta/", "evals/")):
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    fm, body = split_frontmatter(text)
    title = field(fm, "title") or path.stem.replace("-", " ")
    page_type = field(fm, "type") or Path(rel).parts[0]
    aliases = list_field(fm, "aliases")
    entities = list_field(fm, "entities")
    tags = list_field(fm, "tags")
    terms = [*aliases[:3], *entities[:3], *tags[:3], title]
    expected = tuple(dict.fromkeys(term.lower() for term in terms if term and len(term) <= 60))[:6]
    if not expected:
        return None
    if page_type == "claim":
        query = f"請根據 ADA/KDIGO 說明 {title}：哪些是 strong recommendation，哪些證據等級較低？"
        priority = "high"
    elif page_type == "evidence-card":
        query = f"請整理 {title} 的 recommendation number、grade、適用族群與需要查證處。"
        priority = "high"
    elif page_type in {"drug", "concept"}:
        seed = aliases[0] if aliases else title
        query = f"LINE 使用者問「{seed}」時，請用目前 wiki 整理臨床重點與安全限制。"
        priority = "high" if any(term.lower() in {"sglt2i", "glp-1ra", "cgm", "osteoporosis", "sarcopenia"} for term in expected) else "medium"
    elif page_type == "comparison":
        query = f"請比較 {title} 的重點，並標出何時需要回查 raw ADA/KDIGO 原文。"
        priority = "medium"
    else:
        query = f"請根據 {title} 產生一段適合 LINE 的繁中回答，並列出 wiki 依據。"
        priority = "low"
    return SyntheticCase(slugify(rel), query, rel, expected, priority=priority)


def manual_anchor_cases() -> list[SyntheticCase]:
    return [
        SyntheticCase(
            "ckd-evidence-grade-follow-up",
            "58歲第二型糖尿病 eGFR 42 UACR 380，ADA/KDIGO 哪些建議是 strong recommendation，哪些證據等級較低？",
            "claims/ada-kdigo-2026-ckd-cardiorenal-claims.md",
            ("claim registry", "11.7a", "4.3.1", "grade c", "lower-certainty"),
            priority="high",
        ),
        SyntheticCase(
            "line-forbidden-fragment-wording",
            "糖尿病與骨質疏鬆，治療是否與一般人不同？",
            "concepts/diabetes-bone-health-osteoporosis.md",
            ("osteoporosis", "bone health", "fracture", "frax", "t-score"),
            priority="high",
        ),
    ]


def generate(root: Path, limit: int) -> list[SyntheticCase]:
    cases = manual_anchor_cases()
    for path in sorted(root.rglob("*.md")):
        case = page_to_case(root, path)
        if not case:
            continue
        if any(existing.source_page == case.source_page for existing in cases):
            continue
        cases.append(case)
    priority_order = {"high": 0, "medium": 1, "low": 2}
    return sorted(cases, key=lambda case: (priority_order.get(case.priority, 9), case.name))[:limit]


def write_outputs(root: Path, cases: list[SyntheticCase]) -> tuple[Path, Path]:
    today = date.today().isoformat()
    reports = root / "reports"
    evals = root / "evals"
    reports.mkdir(parents=True, exist_ok=True)
    evals.mkdir(parents=True, exist_ok=True)
    jsonl_path = evals / "synthetic-qa-cases.jsonl"
    md_path = reports / "synthetic-qa-candidates.md"
    jsonl_path.write_text(
        "\n".join(json.dumps(case.__dict__, ensure_ascii=False) for case in cases) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Synthetic QA Candidates",
        "",
        f"Generated: {today}",
        "",
        "These are maintenance questions generated from wiki pages. They protect routing, not clinical truth.",
        "",
        "## Cases",
        "",
    ]
    for case in cases:
        expected = ", ".join(case.expected_terms)
        lines.extend(
            [
                f"### {case.name}",
                "",
                f"- Priority: {case.priority}",
                f"- Source page: [[../{case.source_page[:-3]}]]",
                f"- Query: {case.query}",
                f"- Expected terms: {expected}",
                "",
            ]
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path, jsonl_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic QA cases from the LLM Wiki.")
    parser.add_argument("--wiki", type=Path, default=DEFAULT_WIKI)
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    cases = generate(args.wiki, args.limit)
    md_path, jsonl_path = write_outputs(args.wiki, cases)
    if args.json:
        print(json.dumps({"count": len(cases), "report": str(md_path), "jsonl": str(jsonl_path)}, ensure_ascii=False))
    else:
        print(f"Generated {len(cases)} synthetic QA cases")
        print(md_path)
        print(jsonl_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

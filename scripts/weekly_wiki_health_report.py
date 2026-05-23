#!/usr/bin/env python3
from __future__ import annotations

import re
from datetime import date
from pathlib import Path


DEFAULT_WIKI = Path("/Users/ander/Documents/hermes-agent/wiki/ada-kdigo-diabetes-wiki")
REQUIRED_FIELDS = (
    "title",
    "type",
    "created",
    "updated",
    "tags",
    "sources",
    "evidence_level",
    "clinical_use",
    "confidence",
    "last_verified",
    "status",
)


def frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return ""
    match = re.match(r"^---\s*\n(.*?)\n---", text, flags=re.S)
    return match.group(1) if match else ""


def wikilinks(text: str) -> list[str]:
    return re.findall(r"\[\[([^\]|#]+)", text)


def link_exists(root: Path, source: Path, link: str) -> bool:
    if link in {"...", "wikilinks"}:
        return True
    bases = [(source.parent / link).resolve()]
    if not link.startswith("."):
        bases.append((root / link).resolve())
    for base in bases:
        if base.exists() or base.with_suffix(".md").exists():
            return True
    if "/" not in link:
        return any(path.stem == link for path in root.rglob("*.md"))
    return False


def frontmatter_value(fm: str, field: str) -> str:
    match = re.search(rf"^{re.escape(field)}:[ \t]*(.*)$", fm, flags=re.M)
    return match.group(1).strip() if match else ""


def is_resolved_status(fm: str) -> bool:
    return frontmatter_value(fm, "status").strip("'\"").lower() in {"resolved", "retired", "closed", "done"}


def main() -> int:
    root = DEFAULT_WIKI
    report_dir = root / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    pages = sorted(path for path in root.rglob("*.md") if path.is_file())

    missing_frontmatter = []
    metadata_gaps = []
    thin_pages = []
    weak_links = []
    broken_links = []
    stale_pages = []
    low_confidence = []
    open_query_candidates = []
    open_retrieval_failures = []
    open_answer_improvements = []

    today = date.today()
    for path in pages:
        rel = path.relative_to(root).as_posix()
        if rel in {
            "reports/weekly-wiki-health.md",
            "reports/retrieval-failure-analysis.md",
            "reports/answer-improvement-analysis.md",
            "reports/source-freshness-watch.md",
            "reports/synthetic-qa-candidates.md",
            "reports/wiki-self-improvement-audit.md",
        }:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        fm = frontmatter(text)
        body = text.split("---", 2)[-1] if fm else text
        if not fm:
            missing_frontmatter.append(rel)
            continue
        resolved = is_resolved_status(fm)
        for field in REQUIRED_FIELDS:
            if not re.search(rf"^{re.escape(field)}:", fm, flags=re.M):
                metadata_gaps.append(f"{rel}: missing {field}")
        words = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", body)
        if len(words) < 120 and not rel.startswith("raw/"):
            thin_pages.append(f"{rel}: {len(words)} tokens")
        links = wikilinks(text)
        if len(links) < 2 and not rel.startswith("raw/"):
            weak_links.append(f"{rel}: {len(links)} links")
        for link in links:
            if rel.startswith("inbox/"):
                continue
            if not link_exists(root, path, link):
                broken_links.append(f"{rel} -> {link}")
        if re.search(r"confidence:\s*(low|uncertain)", fm) and not (resolved and rel.startswith("inbox/")):
            low_confidence.append(rel)
        if rel.startswith("inbox/query-candidates/") and rel != "inbox/query-candidates/README.md" and not resolved:
            open_query_candidates.append(rel)
        if rel.startswith("inbox/retrieval-failures/") and rel != "inbox/retrieval-failures/README.md" and not resolved:
            open_retrieval_failures.append(rel)
        if rel.startswith("inbox/answer-improvements/") and rel != "inbox/answer-improvements/README.md" and not resolved:
            open_answer_improvements.append(rel)
        match = re.search(r"last_verified:\s*(\d{4}-\d{2}-\d{2})", fm)
        if match:
            try:
                verified = date.fromisoformat(match.group(1))
                if (today - verified).days > 180 and re.search(r"type:\s*(concept|guideline|drug|comparison)", fm):
                    stale_pages.append(f"{rel}: last_verified {verified}")
            except ValueError:
                metadata_gaps.append(f"{rel}: invalid last_verified")

    out = report_dir / "weekly-wiki-health.md"
    sections = [
        "---",
        "title: Weekly Wiki Health Report",
        "summary: Generated weekly health report for LLM Wiki structure, metadata, links, and open inbox queues.",
        "type: report",
        f"created: {today.isoformat()}",
        f"updated: {today.isoformat()}",
        "tags: [llm-wiki, health-check, audit]",
        "sources:",
        "  - reports/wiki-self-improvement-audit.md",
        "  - reports/source-freshness-watch.md",
        "evidence_level: local-practice",
        "clinical_use: workflow",
        "confidence: high",
        f"last_verified: {today.isoformat()}",
        "status: active",
        "obsidian_type: report",
        "aliases:",
        "  - weekly wiki health",
        "entities:",
        "  - Hermes Agent",
        "related:",
        "  - reports/wiki-self-improvement-audit",
        "  - reports/source-freshness-watch",
        "owner_agent: hermes",
        "write_policy: hermes-maintained",
        "---",
        "",
        "# Weekly Wiki Health Report",
        "",
        f"Generated: {today.isoformat()}",
        "",
        "Scope note: Markdown page counts come from the health-report scanner and include maintained wiki pages plus non-raw operational Markdown; registry and normalization reports may use different scopes.",
        "",
        "## Summary",
        "",
        f"- Markdown pages: {len(pages)}",
        f"- Missing frontmatter: {len(missing_frontmatter)}",
        f"- Metadata gaps: {len(metadata_gaps)}",
        f"- Thin pages: {len(thin_pages)}",
        f"- Weak links: {len(weak_links)}",
        f"- Broken links: {len(broken_links)}",
        f"- Stale clinical pages: {len(stale_pages)}",
        f"- Low/uncertain confidence pages: {len(low_confidence)}",
        f"- Open query candidates: {len(open_query_candidates)}",
        f"- Open retrieval failures: {len(open_retrieval_failures)}",
        f"- Open answer improvements: {len(open_answer_improvements)}",
        "",
    ]
    buckets = [
        ("Missing Frontmatter", missing_frontmatter),
        ("Metadata Gaps", metadata_gaps),
        ("Thin Pages", thin_pages),
        ("Weak Links", weak_links),
        ("Broken Links", broken_links),
        ("Stale Clinical Pages", stale_pages),
        ("Low Or Uncertain Confidence", low_confidence),
        ("Open Query Candidates", open_query_candidates),
        ("Open Retrieval Failures", open_retrieval_failures),
        ("Open Answer Improvements", open_answer_improvements),
    ]
    for title, items in buckets:
        sections.extend([f"## {title}", ""])
        if items:
            sections.extend(f"- {item}" for item in items[:80])
            if len(items) > 80:
                sections.append(f"- ... {len(items) - 80} more")
        else:
            sections.append("- None")
        sections.append("")
    sections.extend(
        [
            "## Suggested Next Actions",
            "",
            "- Review broken links before relying on Obsidian graph navigation.",
            "- Promote useful `inbox/query-candidates/` items to `queries/` only after human review.",
            "- Verify exact thresholds against raw ADA/KDIGO Markdown before changing clinical claims.",
            "",
            "## Related Pages",
            "",
            "- [[../reports/wiki-self-improvement-audit]]",
            "- [[../reports/source-freshness-watch]]",
        ]
    )
    out.write_text("\n".join(sections) + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

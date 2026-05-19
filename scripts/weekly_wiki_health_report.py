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

    today = date.today()
    for path in pages:
        rel = path.relative_to(root).as_posix()
        if rel == "reports/weekly-wiki-health.md":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        fm = frontmatter(text)
        body = text.split("---", 2)[-1] if fm else text
        if not fm:
            missing_frontmatter.append(rel)
            continue
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
            if not link_exists(root, path, link):
                broken_links.append(f"{rel} -> {link}")
        if re.search(r"confidence:\s*(low|uncertain)", fm):
            low_confidence.append(rel)
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
        "# Weekly Wiki Health Report",
        "",
        f"Generated: {today.isoformat()}",
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
        ]
    )
    out.write_text("\n".join(sections) + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

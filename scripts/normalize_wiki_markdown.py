#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


DEFAULT_WIKI = Path("/Users/ander/Documents/hermes-agent/wiki/ada-kdigo-diabetes-wiki")

CLINICAL_PREFIXES = {
    "claims",
    "comparisons",
    "concepts",
    "drugs",
    "evidence-cards",
    "evidence-ledger",
    "guidelines",
    "patient-education",
    "queries",
    "teaching",
}

LOW_RISK_PREFIXES = {
    "_meta",
    "docs",
    "evals",
    "inbox",
    "reports",
}

REQUIRED_FIELDS = {
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
    "obsidian_type",
    "aliases",
    "entities",
    "owner_agent",
    "write_policy",
}

RECOMMENDED_FIELDS = {"summary", "related"}


@dataclass
class PageAudit:
    path: str
    prefix: str
    page_type: str
    clinical: bool
    issues: list[str] = field(default_factory=list)
    can_auto_fix: bool = False


def split_frontmatter(text: str) -> tuple[str, str, str]:
    if not text.startswith("---"):
        return "", "", text
    match = re.match(r"^(---\s*\n)(.*?)(\n---\s*\n?)", text, flags=re.S)
    if not match:
        return "", "", text
    return match.group(1), match.group(2), text[match.end() :]


def field_value(frontmatter: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}:[ \t]*(.*)$", frontmatter, flags=re.M)
    return match.group(1).strip().strip("'\"") if match else ""


def list_values(frontmatter: str, key: str) -> list[str]:
    values: list[str] = []
    inline = field_value(frontmatter, key)
    if inline.startswith("[") and inline.endswith("]"):
        values.extend(part.strip().strip("'\"") for part in inline[1:-1].split(",") if part.strip())
    elif inline and inline not in {"[]", "{}"}:
        values.append(inline)
    block = re.search(rf"^{re.escape(key)}:\s*\n((?:\s+- .+\n?)+)", frontmatter, flags=re.M)
    if block:
        values.extend(line.split("-", 1)[1].strip().strip("'\"") for line in block.group(1).splitlines() if "-" in line)
    return [value for value in values if value]


def has_field(frontmatter: str, key: str) -> bool:
    return bool(re.search(rf"^{re.escape(key)}:", frontmatter, flags=re.M))


def wikilink_count(text: str) -> int:
    return len(set(re.findall(r"\[\[([^\]|#]+)", text)))


def heading_count(body: str) -> int:
    return len(re.findall(r"^#{1,3}\s+.+$", body, flags=re.M))


def strip_markdown(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"^---.*?---", " ", text, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]", r"\1", text)
    text = re.sub(r"^#+\s+", "", text, flags=re.M)
    return re.sub(r"\s+", " ", text).strip()


def infer_prefix(path: Path, root: Path) -> str:
    rel = path.relative_to(root).as_posix()
    return rel.split("/", 1)[0] if "/" in rel else "root"


def infer_type(prefix: str, path: Path) -> str:
    if path.name in {"SCHEMA.md", "HERMES.md"}:
        return "workflow"
    if path.name == "index.md":
        return "meta"
    if prefix == "_meta":
        return "meta"
    if prefix == "raw":
        return "source-map"
    if prefix == "mocs":
        return "meta"
    if prefix == "docs":
        return "workflow"
    if prefix == "evidence-cards":
        return "evidence-card"
    if prefix == "evidence-ledger":
        return "evidence-ledger"
    if prefix == "claims":
        return "claim"
    if prefix == "inbox":
        return "research-request"
    if prefix == "reports":
        return "report"
    if prefix == "evals":
        return "workflow"
    return prefix[:-1] if prefix.endswith("s") else prefix


def guess_summary(body: str, limit: int = 220) -> str:
    plain = strip_markdown(body)
    if not plain:
        return "TODO: Add a concise summary describing scope, importance, and when to cite this page."
    return plain[:limit].rstrip() + ("..." if len(plain) > limit else "")


def iter_markdown(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.md")
        if path.is_file()
        and ".git" not in path.parts
        and ".obsidian" not in path.parts
        and not path.name.startswith("Icon")
    )


def audit_page(root: Path, path: Path) -> PageAudit:
    rel = path.relative_to(root).as_posix()
    prefix = infer_prefix(path, root)
    text = path.read_text(encoding="utf-8", errors="ignore")
    _, fm, body = split_frontmatter(text)
    page_type = field_value(fm, "type") or infer_type(prefix, path)
    clinical = prefix in CLINICAL_PREFIXES
    audit = PageAudit(path=rel, prefix=prefix, page_type=page_type, clinical=clinical)

    if prefix == "raw":
        audit.issues.append("raw_file_skip_auto_fix")
        return audit

    if not fm:
        audit.issues.append("missing_frontmatter")
    else:
        missing = sorted(key for key in REQUIRED_FIELDS if not has_field(fm, key))
        for key in missing:
            audit.issues.append(f"missing_field:{key}")
        for key in sorted(RECOMMENDED_FIELDS):
            if not has_field(fm, key):
                audit.issues.append(f"missing_recommended_field:{key}")
        if clinical and not list_values(fm, "sources"):
            audit.issues.append("clinical_missing_sources")
        if clinical and not field_value(fm, "last_verified"):
            audit.issues.append("clinical_missing_last_verified")

    if heading_count(body) < 2 and len(strip_markdown(body)) > 300:
        audit.issues.append("weak_section_structure")
    if prefix not in {"raw", "inbox"} and wikilink_count(text) < 2:
        audit.issues.append("weak_wikilinks")

    auto_fixable = {
        "missing_frontmatter",
        "missing_recommended_field:summary",
        "missing_recommended_field:related",
        "missing_field:aliases",
        "missing_field:entities",
        "missing_field:owner_agent",
        "missing_field:write_policy",
    }
    audit.can_auto_fix = (
        prefix in LOW_RISK_PREFIXES
        and bool(set(audit.issues) & auto_fixable)
        and "raw_file_skip_auto_fix" not in audit.issues
    )
    return audit


def build_frontmatter(root: Path, path: Path, body: str) -> str:
    today = date.today().isoformat()
    prefix = infer_prefix(path, root)
    page_type = infer_type(prefix, path)
    title = path.stem.replace("-", " ").replace("_", " ").title()
    obsidian_type = "report" if prefix == "reports" else "registry" if prefix in {"_meta", "docs", "evals"} else "moc"
    return "\n".join(
        [
            "---",
            f"title: {title}",
            f"summary: {yaml_scalar(guess_summary(body))}",
            f"type: {page_type}",
            f"created: {today}",
            f"updated: {today}",
            "tags: []",
            "sources: []",
            "evidence_level: local-practice",
            "clinical_use: workflow",
            "confidence: low",
            f"last_verified: {today}",
            "status: draft",
            f"obsidian_type: {obsidian_type}",
            "aliases: []",
            "entities: []",
            "related: []",
            "owner_agent: hermes",
            "write_policy: hermes-maintained",
            "---",
            "",
        ]
    ) + "\n"


def yaml_scalar(value: str) -> str:
    if value in {"[]", "{}", "true", "false", "null"}:
        return value
    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        return value
    return json.dumps(value, ensure_ascii=False)


def add_field(frontmatter: str, key: str, value: str) -> str:
    if has_field(frontmatter, key):
        return frontmatter
    return frontmatter.rstrip() + f"\n{key}: {yaml_scalar(value)}\n"


def normalize_page(root: Path, path: Path) -> bool:
    text = path.read_text(encoding="utf-8", errors="ignore")
    start, fm, body = split_frontmatter(text)
    if not fm:
        path.write_text(build_frontmatter(root, path, body) + body.lstrip(), encoding="utf-8")
        return True

    changed = False
    updated = fm
    additions = {
        "summary": guess_summary(body),
        "aliases": "[]",
        "entities": "[]",
        "related": "[]",
        "owner_agent": "hermes",
        "write_policy": "hermes-maintained",
    }
    for key, value in additions.items():
        if not has_field(updated, key):
            updated = add_field(updated, key, value)
            changed = True
    if changed:
        path.write_text(start + updated.rstrip() + "\n---\n\n" + body.lstrip(), encoding="utf-8")
    return changed


def write_report(root: Path, audits: list[PageAudit], changed: list[str]) -> Path:
    report_path = root / "reports" / "markdown-normalization-audit.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    issue_counts: dict[str, int] = {}
    for audit in audits:
        for issue in audit.issues:
            issue_counts[issue] = issue_counts.get(issue, 0) + 1
    lines = [
        "---",
        "title: Markdown Normalization Audit",
        "summary: Generated audit of Markdown page structure gaps for the ADA-KDIGO Diabetes LLM Wiki.",
        "type: report",
        f"created: {date.today().isoformat()}",
        f"updated: {date.today().isoformat()}",
        "tags: [llm-wiki, markdown, audit, normalization]",
        "sources:",
        "  - docs/llm-wiki-markdown-note-standard.md",
        "evidence_level: local-practice",
        "clinical_use: workflow",
        "confidence: high",
        f"last_verified: {date.today().isoformat()}",
        "status: active",
        "obsidian_type: report",
        "aliases:",
        "  - markdown normalization audit",
        "entities:",
        "  - Hermes Agent",
        "related:",
        "  - docs/llm-wiki-markdown-note-standard",
        "  - docs/hermes-md-normalization-schedule",
        "  - SCHEMA",
        "  - HERMES",
        "owner_agent: hermes",
        "write_policy: hermes-maintained",
        "---",
        "",
        "# Markdown Normalization Audit",
        "",
        f"Generated: {date.today().isoformat()}",
        "",
        "## Summary",
        "",
        "- Mode: audit only unless `--apply` was used.",
        "",
        "Scope note: `pages scanned` counts all Markdown files outside `.git` and `.obsidian`, including raw source maps, inbox files, reports, and templates. `_meta/INDEX.json` intentionally excludes raw files, so its page count is smaller.",
        "",
        f"- Pages scanned: {len(audits)}",
        f"- Pages changed in this run: {len(changed)}",
        f"- Pages with auto-fixable low-risk issues: {sum(1 for audit in audits if audit.can_auto_fix)}",
        "- Note: issue counts below include clinical/source-aware gaps that are intentionally not auto-fixed.",
        "",
        "## Issue Counts",
        "",
    ]
    for issue, count in sorted(issue_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- `{issue}`: {count}")
    lines.extend(["", "## Changed Pages", ""])
    if changed:
        lines.extend(f"- [[../{path[:-3]}]]" for path in changed)
    else:
        lines.append("- None")
    lines.extend(["", "## Next Auto-Fixable Pages", ""])
    auto_fixable_pages = [item for item in audits if item.can_auto_fix]
    if auto_fixable_pages:
        for audit in auto_fixable_pages[:20]:
            lines.append(f"- `{audit.path}`: {', '.join(audit.issues)}")
    else:
        lines.append("- None")
    lines.extend(["", "## Clinical Pages Needing Human/Source-Aware Review", ""])
    clinical_needing_review = [audit for audit in audits if audit.clinical and audit.issues]
    if clinical_needing_review:
        for audit in clinical_needing_review[:40]:
            lines.append(f"- `{audit.path}`: {', '.join(audit.issues)}")
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Related Pages",
            "",
            "- [[../docs/llm-wiki-markdown-note-standard]]",
            "- [[../docs/hermes-md-normalization-schedule]]",
            "- [[../SCHEMA]]",
            "- [[../HERMES]]",
            "",
        ]
    )
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit and safely normalize Markdown structure for the LLM Wiki.")
    parser.add_argument("--wiki", type=Path, default=DEFAULT_WIKI)
    parser.add_argument("--apply", action="store_true", help="Apply low-risk automatic fixes.")
    parser.add_argument("--max-files", type=int, default=3, help="Maximum files to modify when --apply is set.")
    parser.add_argument("--write-report", action="store_true", help="Write reports/markdown-normalization-audit.md.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.apply and args.max_files < 1:
        parser.error("--max-files must be >= 1 when --apply is set")

    root = args.wiki.expanduser().resolve()
    audits = [audit_page(root, path) for path in iter_markdown(root)]
    changed: list[str] = []
    if args.apply:
        for audit in [item for item in audits if item.can_auto_fix][: args.max_files]:
            path = root / audit.path
            if normalize_page(root, path):
                changed.append(audit.path)
        audits = [audit_page(root, path) for path in iter_markdown(root)]

    report_path = write_report(root, audits, changed) if args.write_report else None
    result: dict[str, Any] = {
        "pages_scanned": len(audits),
        "pages_changed": len(changed),
        "auto_fixable_pages": sum(1 for audit in audits if audit.can_auto_fix),
        "changed": changed,
        "report": str(report_path) if report_path else "",
        "top_issues": {},
    }
    issue_counts: dict[str, int] = {}
    for audit in audits:
        for issue in audit.issues:
            issue_counts[issue] = issue_counts.get(issue, 0) + 1
    result["top_issues"] = dict(sorted(issue_counts.items(), key=lambda item: (-item[1], item[0]))[:12])

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            f"pages={result['pages_scanned']} changed={result['pages_changed']} "
            f"auto_fixable={result['auto_fixable_pages']}"
        )
        if report_path:
            print(report_path)
        for issue, count in result["top_issues"].items():
            print(f"{issue}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

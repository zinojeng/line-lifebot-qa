#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


DEFAULT_EXCLUDE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".obsidian",
    ".venv",
    "__pycache__",
    "node_modules",
    "vendor",
    "build",
    "dist",
    "cache",
    ".cache",
}

SOURCE_DIRS = {"raw", "sources", "source", "archive", "archives", "originals"}

BASE_FIELDS = (
    "title",
    "summary",
    "type",
    "status",
    "created",
    "updated",
    "tags",
    "aliases",
    "sources",
    "related",
    "confidence",
    "last_verified",
)

PROFILE_EXTRA_FIELDS: dict[str, tuple[str, ...]] = {
    "generic": (),
    "obsidian": ("obsidian_type",),
    "project": ("owner", "owner_agent", "write_policy"),
    "research": ("source_type", "provenance", "open_questions"),
    "medical": ("evidence_level", "clinical_use", "contested", "review_cycle_days"),
}

PROFILE_DEFAULTS: dict[str, dict[str, str]] = {
    "generic": {
        "type": "note",
        "status": "draft",
        "tags": "[]",
        "aliases": "[]",
        "sources": "[]",
        "related": "[]",
        "confidence": "medium",
        "owner_agent": "hermes",
        "write_policy": "maintainer-reviewed",
    },
    "obsidian": {
        "obsidian_type": "note",
    },
    "project": {
        "owner": "unassigned",
        "owner_agent": "hermes",
        "write_policy": "maintainer-reviewed",
    },
    "research": {
        "source_type": "note",
        "provenance": "[]",
        "open_questions": "[]",
    },
    "medical": {
        "evidence_level": "needs-source",
        "clinical_use": "reference",
        "contested": "false",
        "review_cycle_days": "180",
    },
}

HIGH_RISK_PROFILE_NAMES = {"medical"}
HIGH_RISK_TERMS = {
    "contraindication",
    "dose",
    "dosage",
    "guideline",
    "recommendation",
    "threshold",
    "grade",
    "治療",
    "禁忌",
    "劑量",
    "建議等級",
    "證據等級",
}


@dataclass
class PageAudit:
    path: str
    prefix: str
    page_type: str
    source_like: bool
    high_risk: bool
    issues: list[str] = field(default_factory=list)
    can_auto_fix: bool = False


def split_frontmatter(text: str) -> tuple[str, str, str]:
    if not text.startswith("---"):
        return "", "", text
    match = re.match(r"^(---\s*\n)(.*?)(\n---\s*\n?)", text, flags=re.S)
    if not match:
        return "", "", text
    return match.group(1), match.group(2), text[match.end() :]


def has_field(frontmatter: str, key: str) -> bool:
    return bool(re.search(rf"^{re.escape(key)}:", frontmatter, flags=re.M))


def field_value(frontmatter: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}:[ \t]*(.*)$", frontmatter, flags=re.M)
    return match.group(1).strip().strip("'\"") if match else ""


def strip_markdown(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"^---.*?---", " ", text, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]", r"\1", text)
    text = re.sub(r"^#+\s+", "", text, flags=re.M)
    return re.sub(r"\s+", " ", text).strip()


def wikilink_count(text: str) -> int:
    return len(set(re.findall(r"\[\[([^\]|#]+)", text)))


def heading_count(body: str) -> int:
    return len(re.findall(r"^#{1,3}\s+.+$", body, flags=re.M))


def infer_prefix(path: Path, root: Path) -> str:
    rel = path.relative_to(root).as_posix()
    return rel.split("/", 1)[0] if "/" in rel else "root"


def infer_type(path: Path, prefix: str) -> str:
    name = path.name.lower()
    if name in {"readme.md", "index.md"}:
        return "index"
    if name in {"agents.md", "hermes.md", "claude.md", "schema.md"}:
        return "workflow"
    if prefix in {"docs", "documentation"}:
        return "workflow"
    if prefix in {"mocs", "moc"}:
        return "moc"
    if prefix in SOURCE_DIRS:
        return "source"
    if prefix in {"projects", "project"}:
        return "project"
    if prefix in {"queries", "qa"}:
        return "query"
    return "note"


def title_from_path(path: Path) -> str:
    return path.stem.replace("-", " ").replace("_", " ").strip().title()


def summary_from_body(body: str, limit: int = 220) -> str:
    plain = strip_markdown(body)
    if not plain:
        return "TODO: Add a concise summary describing scope, importance, and when this page should be used."
    return plain[:limit].rstrip() + ("..." if len(plain) > limit else "")


def fields_for_profile(profile: str) -> tuple[str, ...]:
    extras = PROFILE_EXTRA_FIELDS.get(profile, ())
    return tuple(dict.fromkeys((*BASE_FIELDS, *extras)))


def defaults_for_profile(profile: str) -> dict[str, str]:
    defaults = dict(PROFILE_DEFAULTS["generic"])
    defaults.update(PROFILE_DEFAULTS.get(profile, {}))
    return defaults


def iter_markdown(root: Path, exclude_dirs: set[str]) -> list[Path]:
    paths: list[Path] = []
    for path in root.rglob("*.md"):
        if not path.is_file():
            continue
        if any(part in exclude_dirs for part in path.relative_to(root).parts):
            continue
        if path.name.startswith("Icon"):
            continue
        paths.append(path)
    return sorted(paths)


def audit_page(root: Path, path: Path, profile: str, include_sources: bool) -> PageAudit:
    rel = path.relative_to(root).as_posix()
    prefix = infer_prefix(path, root)
    text = path.read_text(encoding="utf-8", errors="ignore")
    _, frontmatter, body = split_frontmatter(text)
    page_type = field_value(frontmatter, "type") or infer_type(path, prefix)
    source_like = prefix in SOURCE_DIRS or page_type == "source"
    high_risk = profile in HIGH_RISK_PROFILE_NAMES or any(term.lower() in text.lower() for term in HIGH_RISK_TERMS)
    audit = PageAudit(path=rel, prefix=prefix, page_type=page_type, source_like=source_like, high_risk=high_risk)

    if source_like and not include_sources:
        audit.issues.append("source_like_skip_auto_fix")

    if not frontmatter:
        audit.issues.append("missing_frontmatter")
    else:
        for key in fields_for_profile(profile):
            if not has_field(frontmatter, key):
                audit.issues.append(f"missing_field:{key}")
        if has_field(frontmatter, "summary") and not field_value(frontmatter, "summary"):
            audit.issues.append("empty_field:summary")

    if heading_count(body) < 2 and len(strip_markdown(body)) > 300:
        audit.issues.append("weak_section_structure")
    if profile == "obsidian" and not source_like and wikilink_count(text) < 2:
        audit.issues.append("weak_wikilinks")

    low_risk_issues = {
        "missing_frontmatter",
        "missing_field:title",
        "missing_field:summary",
        "missing_field:type",
        "missing_field:status",
        "missing_field:created",
        "missing_field:updated",
        "missing_field:tags",
        "missing_field:aliases",
        "missing_field:sources",
        "missing_field:related",
        "missing_field:confidence",
        "missing_field:last_verified",
        "missing_field:obsidian_type",
        "missing_field:owner",
        "missing_field:owner_agent",
        "missing_field:write_policy",
        "empty_field:summary",
    }
    audit.can_auto_fix = bool(set(audit.issues) & low_risk_issues) and (include_sources or not source_like) and not high_risk
    return audit


def yaml_value_for(key: str, path: Path, body: str, profile: str) -> str:
    today = date.today().isoformat()
    prefix = path.parts[0] if path.parts else "root"
    defaults = defaults_for_profile(profile)
    if key == "title":
        return title_from_path(path)
    if key == "summary":
        return summary_from_body(body)
    if key == "created" or key == "updated" or key == "last_verified":
        return today
    if key == "type":
        return infer_type(path, prefix)
    return defaults.get(key, "[]")


def yaml_scalar(value: str) -> str:
    if value in {"[]", "{}", "true", "false", "null"}:
        return value
    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        return value
    return json.dumps(value, ensure_ascii=False)


def build_frontmatter(root: Path, path: Path, body: str, profile: str) -> str:
    rel = path.relative_to(root)
    lines = ["---"]
    for key in fields_for_profile(profile):
        lines.append(f"{key}: {yaml_scalar(yaml_value_for(key, rel, body, profile))}")
    lines.extend(["---", ""])
    return "\n".join(lines)


def add_missing_field(frontmatter: str, key: str, value: str) -> str:
    if has_field(frontmatter, key):
        return frontmatter
    return frontmatter.rstrip() + f"\n{key}: {yaml_scalar(value)}\n"


def normalize_page(root: Path, path: Path, profile: str) -> bool:
    text = path.read_text(encoding="utf-8", errors="ignore")
    start, frontmatter, body = split_frontmatter(text)
    if not frontmatter:
        path.write_text(build_frontmatter(root, path, body, profile) + body.lstrip(), encoding="utf-8")
        return True

    changed = False
    updated = frontmatter
    rel = path.relative_to(root)
    for key in fields_for_profile(profile):
        if not has_field(updated, key) or (key == "summary" and not field_value(updated, key)):
            updated = add_missing_field(updated, key, yaml_value_for(key, rel, body, profile))
            changed = True
    if changed:
        path.write_text(start + updated.rstrip() + "\n---\n" + body, encoding="utf-8")
    return changed


def write_report(root: Path, audits: list[PageAudit], changed: list[str], profile: str, report: Path) -> Path:
    issue_counts: dict[str, int] = {}
    for audit in audits:
        for issue in audit.issues:
            issue_counts[issue] = issue_counts.get(issue, 0) + 1
    report = report if report.is_absolute() else root / report
    report.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        "title: Markdown Normalization Audit",
        "summary: Generated audit of Markdown structure gaps for an LLM Wiki or Markdown knowledge project.",
        "type: workflow",
        f"created: {date.today().isoformat()}",
        f"updated: {date.today().isoformat()}",
        "tags: [llm-wiki, markdown, audit, normalization]",
        "sources: []",
        "status: active",
        "confidence: high",
        f"last_verified: {date.today().isoformat()}",
        "---",
        "",
        "# Markdown Normalization Audit",
        "",
        f"Generated: {date.today().isoformat()}",
        f"Profile: `{profile}`",
        "",
        "## Summary",
        "",
        "- Mode: audit only unless `--apply` was used.",
        f"- Pages scanned: {len(audits)}",
        f"- Pages changed in this run: {len(changed)}",
        f"- Auto-fixable low-risk pages: {sum(1 for audit in audits if audit.can_auto_fix)}",
        "",
        "## Issue Counts",
        "",
    ]
    for issue, count in sorted(issue_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- `{issue}`: {count}")
    lines.extend(["", "## Changed Pages", ""])
    lines.extend([f"- `{path}`" for path in changed] or ["- None"])
    lines.extend(["", "## Next Auto-Fixable Pages", ""])
    for audit in [item for item in audits if item.can_auto_fix][:30]:
        lines.append(f"- `{audit.path}`: {', '.join(audit.issues)}")
    lines.extend(["", "## Needs Human Or Source-Aware Review", ""])
    needs_review = [audit for audit in audits if audit.issues and not audit.can_auto_fix]
    for audit in needs_review[:60]:
        flags = []
        if audit.high_risk:
            flags.append("high-risk")
        if audit.source_like:
            flags.append("source-like")
        label = f" ({', '.join(flags)})" if flags else ""
        lines.append(f"- `{audit.path}`{label}: {', '.join(audit.issues)}")
    if not needs_review:
        lines.append("- None")
    lines.append("")
    report.write_text("\n".join(lines), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Generic Markdown normalizer for LLM Wiki-style projects.")
    parser.add_argument("--root", "--wiki", dest="root", type=Path, required=True, help="Project/wiki root containing Markdown files.")
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILE_EXTRA_FIELDS),
        default="generic",
        help="Field preset to use for audit and low-risk normalization.",
    )
    parser.add_argument("--apply", action="store_true", help="Apply low-risk fixes. Default is audit only.")
    parser.add_argument("--max-files", type=int, default=3, help="Maximum files to modify when --apply is set.")
    parser.add_argument("--include-sources", action="store_true", help="Allow auto-fix in source-like directories such as raw/ or sources/.")
    parser.add_argument("--exclude-dir", action="append", default=[], help="Additional directory name to exclude. Can be repeated.")
    parser.add_argument("--report", type=Path, default=Path("reports/markdown-normalization-audit.md"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.apply and args.max_files < 1:
        parser.error("--max-files must be >= 1 when --apply is set")

    root = args.root.expanduser().resolve()
    exclude_dirs = set(DEFAULT_EXCLUDE_DIRS) | set(args.exclude_dir)
    paths = iter_markdown(root, exclude_dirs)
    audits = [audit_page(root, path, args.profile, args.include_sources) for path in paths]
    changed: list[str] = []
    if args.apply:
        for audit in [item for item in audits if item.can_auto_fix][: args.max_files]:
            path = root / audit.path
            if normalize_page(root, path, args.profile):
                changed.append(audit.path)
        audits = [audit_page(root, path, args.profile, args.include_sources) for path in paths]
    report = write_report(root, audits, changed, args.profile, args.report)

    issue_counts: dict[str, int] = {}
    for audit in audits:
        for issue in audit.issues:
            issue_counts[issue] = issue_counts.get(issue, 0) + 1
    result: dict[str, Any] = {
        "root": str(root),
        "profile": args.profile,
        "pages_scanned": len(audits),
        "pages_changed": len(changed),
        "auto_fixable_pages": sum(1 for audit in audits if audit.can_auto_fix),
        "changed": changed,
        "report": str(report),
        "top_issues": dict(sorted(issue_counts.items(), key=lambda item: (-item[1], item[0]))[:12]),
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            f"root={result['root']} profile={result['profile']} pages={result['pages_scanned']} "
            f"changed={result['pages_changed']} auto_fixable={result['auto_fixable_pages']}"
        )
        print(report)
        for issue, count in result["top_issues"].items():
            print(f"{issue}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

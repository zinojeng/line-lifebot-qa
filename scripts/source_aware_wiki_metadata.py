#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
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
    "queries",
    "teaching",
}
VAULT_ROUTE_PREFIXES = {
    "_meta",
    "claims",
    "comparisons",
    "concepts",
    "docs",
    "drugs",
    "evidence-cards",
    "evidence-ledger",
    "evals",
    "guidelines",
    "mocs",
    "patient-education",
    "queries",
    "reports",
    "teaching",
}


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


def yaml_scalar(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def yaml_list(values: list[str]) -> str:
    if not values:
        return "[]"
    return "\n" + "\n".join(f"  - {yaml_scalar(value)}" for value in values)


def add_field(frontmatter: str, key: str, value: str) -> str:
    if has_field(frontmatter, key):
        return frontmatter
    return frontmatter.rstrip() + f"\n{key}: {value}\n"


def replace_field(frontmatter: str, key: str, value: str) -> str:
    block_pattern = rf"^{re.escape(key)}:\s*\n(?:\s+- .+\n?)+"
    if re.search(block_pattern, frontmatter, flags=re.M):
        return re.sub(block_pattern, f"{key}: {value}\n", frontmatter, count=1, flags=re.M)
    line_pattern = rf"^{re.escape(key)}:[^\n]*(?:\n|$)"
    if re.search(line_pattern, frontmatter, flags=re.M):
        return re.sub(line_pattern, f"{key}: {value}\n", frontmatter, count=1, flags=re.M)
    return add_field(frontmatter, key, value)


def title_for(path: Path, frontmatter: str) -> str:
    return field_value(frontmatter, "title") or path.stem.replace("-", " ").replace("_", " ").title()


def page_type_for(path: Path, frontmatter: str) -> str:
    prefix = path.parts[0] if path.parts else ""
    return field_value(frontmatter, "type") or (prefix[:-1] if prefix.endswith("s") else prefix)


def neutral_summary(path: Path, frontmatter: str) -> str:
    title = title_for(path, frontmatter)
    page_type = page_type_for(path, frontmatter)
    source_count = len(list_values(frontmatter, "sources"))
    source_phrase = f"{source_count} listed source(s)" if source_count else "listed sources"
    return (
        f"Source-aware {page_type} page for {title}; use it for ADA/KDIGO diabetes wiki retrieval, "
        f"then verify exact clinical claims against {source_phrase} before changing recommendations."
    )


def clean_route(route: str) -> str:
    route = route.strip().strip("'\"")
    if route.endswith(".md"):
        route = route[:-3]
    if not route or route in {"...", "wikilinks"} or route.startswith(("/", "~")):
        return ""
    while route.startswith("../"):
        route = route[3:]
    if route.startswith(".") or ".." in Path(route).parts:
        return ""
    prefix = route.split("/", 1)[0]
    if prefix not in VAULT_ROUTE_PREFIXES:
        return ""
    return route


def existing_routes(frontmatter: str, body: str) -> list[str]:
    routes: list[str] = []
    for link in re.findall(r"\[\[([^\]|#]+)", body):
        link = clean_route(link)
        if link and link not in routes:
            routes.append(link)
    for source in list_values(frontmatter, "sources"):
        candidate = clean_route(source)
        if candidate and candidate not in routes:
            routes.append(candidate)
    return routes[:6]


def merged_related(frontmatter: str, body: str) -> list[str]:
    routes: list[str] = []
    for value in list_values(frontmatter, "related"):
        raw = value.strip().strip("'\"")
        cleaned = clean_route(raw)
        candidate = cleaned or raw
        if candidate and candidate not in {"...", "wikilinks"} and candidate not in routes:
            routes.append(candidate)
    for route in existing_routes(frontmatter, body):
        if route not in routes:
            routes.append(route)
    return routes[:10]


def current_related_needs_cleanup(frontmatter: str) -> bool:
    if not has_field(frontmatter, "related"):
        return False
    values = list_values(frontmatter, "related")
    cleaned = [clean_route(value) for value in values]
    cleaned = [value for value in cleaned if value]
    return values != list(dict.fromkeys(cleaned))


def conservative_aliases(path: Path, frontmatter: str) -> list[str]:
    title = title_for(path, frontmatter)
    stem = path.stem
    aliases = []
    title_key = title.casefold().strip()
    for value in (stem.replace("-", " "),):
        key = value.casefold().strip()
        if value and key != title_key and key not in {alias.casefold().strip() for alias in aliases}:
            aliases.append(value)
    return aliases[:3]


def conservative_entities(frontmatter: str) -> list[str]:
    tags = list_values(frontmatter, "tags")
    stop_terms = {
        "2025",
        "2026",
        "ada",
        "clinical practice",
        "comparison",
        "evidence quality",
        "guideline",
        "implementation",
        "limitations",
        "methodology",
        "relationship",
        "reimbursement",
        "standards of care",
        "teaching",
        "wiki",
    }
    entities = []
    for tag in tags:
        normalized = tag.replace("-", " ").strip()
        key = normalized.lower()
        if normalized and key not in stop_terms and key not in {item.lower() for item in entities}:
            entities.append(normalized)
    return entities[:6]


def target_pages(root: Path) -> list[Path]:
    pages = []
    for path in sorted(root.rglob("*.md")):
        if not path.is_file() or ".git" in path.parts or ".obsidian" in path.parts or path.name.startswith("Icon"):
            continue
        rel = path.relative_to(root)
        prefix = rel.parts[0] if rel.parts else ""
        if prefix in CLINICAL_PREFIXES:
            pages.append(path)
    return pages


def normalize_page(root: Path, path: Path) -> bool:
    text = path.read_text(encoding="utf-8", errors="ignore")
    start, fm, body = split_frontmatter(text)
    if not fm:
        return False
    rel = path.relative_to(root)
    updated = fm
    changed = False
    if not has_field(updated, "summary"):
        updated = add_field(updated, "summary", yaml_scalar(neutral_summary(rel, updated)))
        changed = True
    if not has_field(updated, "related") or current_related_needs_cleanup(updated):
        updated = replace_field(updated, "related", yaml_list(merged_related(updated, body)))
        changed = True
    if not has_field(updated, "aliases"):
        updated = add_field(updated, "aliases", yaml_list(conservative_aliases(rel, updated)))
        changed = True
    if not has_field(updated, "entities"):
        updated = add_field(updated, "entities", yaml_list(conservative_entities(updated)))
        changed = True
    if not has_field(updated, "owner_agent"):
        updated = add_field(updated, "owner_agent", "hermes")
        changed = True
    if not has_field(updated, "write_policy"):
        updated = add_field(updated, "write_policy", "source-aware-review")
        changed = True
    if changed:
        path.write_text(start + updated.rstrip() + "\n---\n\n" + body.lstrip(), encoding="utf-8")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Source-aware metadata filler for clinical LLM Wiki pages.")
    parser.add_argument("--wiki", type=Path, default=DEFAULT_WIKI)
    parser.add_argument("--max-files", type=int, default=5)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = args.wiki.expanduser().resolve()
    candidates: list[str] = []
    changed: list[str] = []
    for path in target_pages(root):
        text = path.read_text(encoding="utf-8", errors="ignore")
        _, fm, _ = split_frontmatter(text)
        if not fm:
            continue
        needed = [key for key in ("summary", "related", "aliases", "entities", "owner_agent", "write_policy") if not has_field(fm, key)]
        if current_related_needs_cleanup(fm):
            needed.append("related_cleanup")
        if needed:
            rel = path.relative_to(root).as_posix()
            candidates.append(rel)
            if args.apply and len(changed) < args.max_files and normalize_page(root, path):
                changed.append(rel)
    result: dict[str, Any] = {"candidates": len(candidates), "changed": changed, "remaining_after_run": max(0, len(candidates) - len(changed))}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"candidates={result['candidates']} changed={len(changed)} remaining_after_run={result['remaining_after_run']}")
        for item in changed:
            print(item)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

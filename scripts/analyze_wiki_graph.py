#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any


DEFAULT_WIKI = Path("/Users/ander/Documents/hermes-agent/wiki/ada-kdigo-diabetes-wiki")

CORE_NAV_FILES = (
    "index.md",
    "_meta/topic-map.md",
    "_meta/aliases.md",
    "_meta/typed-relationships.md",
)

MOC_TYPES = {"meta", "workflow"}
ROUTE_WORTHY_PREFIXES = {
    "claims",
    "comparisons",
    "concepts",
    "drugs",
    "evidence-cards",
    "evidence-ledger",
    "guidelines",
    "teaching",
    "queries",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def strip_md(path: str) -> str:
    return path[:-3] if path.endswith(".md") else path


def normalize_link(link: str) -> str:
    link = link.strip().split("#", 1)[0].split("|", 1)[0]
    while link.startswith("../"):
        link = link[3:]
    return strip_md(link)


def wikilinks(text: str) -> set[str]:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    ignored = {"...", "wikilinks", "related-page-1", "related-page-2", "related-concept-a", "related-concept-b"}
    return {
        normalize_link(match)
        for match in re.findall(r"\[\[([^\]]+)\]\]", text)
        if match.strip() and normalize_link(match) not in ignored
    }


def split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---"):
        return "", text
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, flags=re.S)
    if not match:
        return "", text
    return match.group(1), text[match.end() :]


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


def related_links(text: str) -> set[str]:
    frontmatter, _ = split_frontmatter(text)
    return {normalize_link(value) for value in list_values(frontmatter, "related") if normalize_link(value)}


def text_contains_route(text: str, path: str) -> bool:
    stem = strip_md(path)
    return stem in text or Path(stem).name in text


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""


def resolve_existing(paths: set[str], link: str) -> str | None:
    candidates = [link, f"{link}.md"]
    name = Path(link).name
    for path in paths:
        stem = strip_md(path)
        if stem in candidates or Path(stem).name == name:
            return path
    return None


def analyze(root: Path) -> dict[str, Any]:
    page_registry = load_json(root / "_meta" / "page-registry.json")
    pages_by_path = {page["path"]: page for page in page_registry}
    all_paths = {path.relative_to(root).as_posix() for path in root.rglob("*.md") if ".git" not in path.parts}
    inbound: dict[str, set[str]] = defaultdict(set)
    broken: list[dict[str, str]] = []
    broken_related: list[dict[str, str]] = []
    links_by_path: dict[str, set[str]] = {}
    related_by_path: dict[str, set[str]] = {}
    for page in page_registry:
        source = page["path"]
        text = read_text(root / source)
        source_links = wikilinks(text)
        source_related = related_links(text)
        links_by_path[source] = source_links
        related_by_path[source] = source_related
        for link in source_links:
            normalized = normalize_link(link)
            target = resolve_existing(all_paths, normalized)
            if target:
                inbound[target].add(source)
            else:
                broken.append({"source": source, "target": link})
        for link in source_related:
            target = resolve_existing(all_paths, link)
            if target:
                inbound[target].add(source)
            else:
                broken_related.append({"source": source, "target": link})

    nav_text = "\n".join(read_text(root / file) for file in CORE_NAV_FILES)
    moc_text = "\n".join(read_text(path) for path in sorted((root / "mocs").glob("*.md"))) if (root / "mocs").exists() else ""
    alias_text = read_text(root / "_meta" / "aliases.md")
    relationship_text = read_text(root / "_meta" / "typed-relationships.md")

    orphan_pages = []
    weak_link_pages = []
    missing_moc_routes = []
    missing_alias_routes = []
    missing_relationship_edges = []
    duplicate_candidates: dict[str, list[str]] = defaultdict(list)
    entity_counter: Counter[str] = Counter()

    for page in page_registry:
        path = page["path"]
        prefix = path.split("/", 1)[0] if "/" in path else "root"
        page_type = str(page.get("type", ""))
        aliases = page.get("aliases", []) or []
        entities = page.get("entities", []) or []
        links = links_by_path.get(path, set())
        duplicate_key = re.sub(r"[^a-z0-9]+", "-", str(page.get("title", "")).lower()).strip("-")
        if duplicate_key:
            duplicate_candidates[duplicate_key].append(path)
        for entity in entities:
            entity_counter[str(entity)] += 1

        if prefix in {"_meta", "reports", "inbox", "raw"} or path in CORE_NAV_FILES:
            continue
        if not inbound.get(path) and page_type not in MOC_TYPES:
            orphan_pages.append(path)
        if len(links) < 2 and prefix not in {"raw", "inbox"}:
            weak_link_pages.append(path)
        if prefix in ROUTE_WORTHY_PREFIXES and not text_contains_route(nav_text + "\n" + moc_text, path):
            missing_moc_routes.append(path)
        if prefix in ROUTE_WORTHY_PREFIXES and not aliases and not text_contains_route(alias_text, path):
            missing_alias_routes.append(path)
        if prefix in ROUTE_WORTHY_PREFIXES and not text_contains_route(relationship_text, path):
            missing_relationship_edges.append(path)

    duplicates = {key: paths for key, paths in duplicate_candidates.items() if len(paths) > 1}
    return {
        "page_count": len(page_registry),
        "inbound_count": {path: len(sources) for path, sources in inbound.items()},
        "orphan_pages": sorted(orphan_pages),
        "weak_link_pages": sorted(weak_link_pages),
        "broken_wikilinks": broken,
        "broken_related": broken_related,
        "missing_moc_routes": sorted(missing_moc_routes),
        "missing_alias_routes": sorted(missing_alias_routes),
        "missing_relationship_edges": sorted(missing_relationship_edges),
        "duplicate_title_candidates": duplicates,
        "top_entities": entity_counter.most_common(25),
    }


def write_report(root: Path, result: dict[str, Any]) -> Path:
    report = root / "reports" / "wiki-graph-rebuild-audit.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        "title: Wiki Graph Rebuild Audit",
        "summary: Graph-oriented audit of Obsidian/LLM Wiki links, MOC routes, aliases, typed relationships, orphan pages, and weak-link pages.",
        "type: report",
        f"created: {date.today().isoformat()}",
        f"updated: {date.today().isoformat()}",
        "tags: [llm-wiki, obsidian, graph, moc, aliases, relationships]",
        "sources:",
        "  - _meta/page-registry.json",
        "  - _meta/topic-map.md",
        "  - _meta/aliases.md",
        "  - _meta/typed-relationships.md",
        "evidence_level: local-practice",
        "clinical_use: workflow",
        "confidence: high",
        f"last_verified: {date.today().isoformat()}",
        "status: active",
        "obsidian_type: report",
        "aliases:",
        "  - graph rebuild audit",
        "  - Obsidian graph audit",
        "entities:",
        "  - Hermes Agent",
        "  - Obsidian",
        "related:",
        "  - _meta/topic-map",
        "  - _meta/aliases",
        "  - _meta/typed-relationships",
        "owner_agent: hermes",
        "write_policy: hermes-maintained",
        "---",
        "",
        "# Wiki Graph Rebuild Audit",
        "",
        f"Generated: {date.today().isoformat()}",
        "",
        "## Summary",
        "",
        f"- Registry pages analyzed: {result['page_count']}",
        f"- Orphan pages: {len(result['orphan_pages'])}",
        f"- Weak-link pages: {len(result['weak_link_pages'])}",
        f"- Broken wikilinks: {len(result['broken_wikilinks'])}",
        f"- Broken related entries: {len(result['broken_related'])}",
        f"- Pages missing MOC/topic route: {len(result['missing_moc_routes'])}",
        f"- Pages missing alias route: {len(result['missing_alias_routes'])}",
        f"- Pages missing typed relationship edge: {len(result['missing_relationship_edges'])}",
        f"- Duplicate title candidate groups: {len(result['duplicate_title_candidates'])}",
        "",
        "## Immediate Graph Tasks",
        "",
        "1. Add or update MOC/topic-map routes for route-worthy pages missing navigation.",
        "2. Add aliases only for pages likely to be queried directly by LINE users or Hermes.",
        "3. Add typed relationship edges before creating new pages when the page already exists.",
        "4. Keep clinical claim changes source-aware; graph repair should not alter recommendation numbers, grades, thresholds, or safety language.",
        "",
    ]
    sections = [
        ("Orphan Pages", "orphan_pages"),
        ("Weak-Link Pages", "weak_link_pages"),
        ("Broken Wikilinks", "broken_wikilinks"),
        ("Broken Related Entries", "broken_related"),
        ("Pages Missing MOC Or Topic Route", "missing_moc_routes"),
        ("Pages Missing Alias Route", "missing_alias_routes"),
        ("Pages Missing Typed Relationship Edge", "missing_relationship_edges"),
    ]
    for title, key in sections:
        lines.extend([f"## {title}", ""])
        values = result[key]
        if not values:
            lines.append("- None")
        elif key in {"broken_wikilinks", "broken_related"}:
            for item in values[:80]:
                lines.append(f"- `{item['source']}` -> `{item['target']}`")
        else:
            for path in values[:80]:
                lines.append(f"- [[../{strip_md(path)}]]")
        lines.append("")
    lines.extend(["## Duplicate Title Candidates", ""])
    if result["duplicate_title_candidates"]:
        for key, paths in result["duplicate_title_candidates"].items():
            lines.append(f"- `{key}`: " + ", ".join(f"`{path}`" for path in paths))
    else:
        lines.append("- None")
    lines.extend(["", "## Top Entities", ""])
    if result["top_entities"]:
        for entity, count in result["top_entities"]:
            lines.append(f"- `{entity}`: {count}")
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Related Pages",
            "",
            "- [[../_meta/topic-map]]",
            "- [[../_meta/aliases]]",
            "- [[../_meta/typed-relationships]]",
            "- [[../reports/markdown-normalization-audit]]",
            "",
        ]
    )
    report.write_text("\n".join(lines), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze Obsidian/LLM Wiki graph routes and relationship gaps.")
    parser.add_argument("--wiki", type=Path, default=DEFAULT_WIKI)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = args.wiki.expanduser().resolve()
    result = analyze(root)
    report = write_report(root, result)
    summary = {
        "page_count": result["page_count"],
        "orphan_pages": len(result["orphan_pages"]),
        "weak_link_pages": len(result["weak_link_pages"]),
        "broken_wikilinks": len(result["broken_wikilinks"]),
        "broken_related": len(result["broken_related"]),
        "missing_moc_routes": len(result["missing_moc_routes"]),
        "missing_alias_routes": len(result["missing_alias_routes"]),
        "missing_relationship_edges": len(result["missing_relationship_edges"]),
        "duplicate_title_candidate_groups": len(result["duplicate_title_candidates"]),
        "report": str(report),
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        for key, value in summary.items():
            print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

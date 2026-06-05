#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_WIKI = Path("/Users/ander/Documents/hermes-agent/wiki/ada-kdigo-diabetes-wiki")
CORE_ROUTE_FILES = (
    "index.md",
    "_meta/topic-map.md",
    "_meta/aliases.md",
    "_meta/typed-relationships.md",
)
ROUTE_WORTHY_PREFIXES = {
    "claims",
    "comparisons",
    "concepts",
    "drugs",
    "evidence-cards",
    "evidence-ledger",
    "guidelines",
    "mocs",
    "patient-education",
    "queries",
    "teaching",
}


@dataclass
class EdgeSignal:
    source: str
    target: str
    score: float
    signals: Counter[str]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""


def strip_md(path: str) -> str:
    return path[:-3] if path.endswith(".md") else path


def normalize_link(link: str) -> str:
    link = link.strip().split("#", 1)[0].split("|", 1)[0].strip().strip("'\"")
    while link.startswith("../"):
        link = link[3:]
    return strip_md(link)


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


def wikilinks(text: str) -> list[str]:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    ignored = {"...", "wikilinks", "related-page-1", "related-page-2", "related-concept-a", "related-concept-b"}
    links = []
    for match in re.findall(r"\[\[([^\]]+)\]\]", text):
        normalized = normalize_link(match)
        if normalized and normalized not in ignored:
            links.append(normalized)
    return sorted(set(links))


def section(text: str, heading: str) -> str:
    pattern = rf"^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, text, flags=re.M | re.S)
    return match.group(1).strip() if match else ""


def bullet_value(text: str, label: str) -> str:
    match = re.search(rf"^- {re.escape(label)}:\s*(.*)$", text, flags=re.M)
    return match.group(1).strip() if match else ""


def frontmatter_status(text: str) -> str:
    fm, _ = split_frontmatter(text)
    return field_value(fm, "status").lower()


def resolve_page(all_paths: set[str], link: str) -> str | None:
    normalized = normalize_link(link)
    candidates = {normalized, f"{normalized}.md"}
    basename = Path(normalized).name
    basename_matches: list[str] = []
    for path in all_paths:
        stem = strip_md(path)
        if path in candidates or stem in candidates:
            return path
        if Path(stem).name == basename:
            basename_matches.append(path)
    if len(basename_matches) == 1:
        return basename_matches[0]
    return None


def edge_key(source: str, target: str) -> tuple[str, str]:
    return source, target


def add_signal(edges: dict[tuple[str, str], EdgeSignal], source: str, target: str, signal: str, weight: float) -> None:
    key = edge_key(source, target)
    if key not in edges:
        edges[key] = EdgeSignal(source=source, target=target, score=0.0, signals=Counter())
    edges[key].score += weight
    edges[key].signals[signal] += 1


def page_indexes(registry: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    pages = {str(page["path"]): page for page in registry}
    title_to_path: dict[str, str] = {}
    for page in registry:
        path = str(page["path"])
        title = str(page.get("title", "")).lower()
        if title:
            title_to_path[title] = path
        title_to_path[Path(path).stem.replace("-", " ").lower()] = path
    return pages, title_to_path


def source_line_to_page(line: str, title_to_path: dict[str, str]) -> str | None:
    lower = line.lower()
    for title, path in sorted(title_to_path.items(), key=lambda item: len(item[0]), reverse=True):
        if title and title in lower:
            return path
    match = re.search(r"wiki_page:([^\s,]+\.md)", line)
    if match:
        return match.group(1)
    return None


def build_structural_edges(root: Path, pages: dict[str, dict[str, Any]], edges: dict[tuple[str, str], EdgeSignal]) -> None:
    all_paths = set(pages)
    nav_text = "\n".join(read_text(root / name) for name in CORE_ROUTE_FILES)
    for source in sorted(pages):
        text = read_text(root / source)
        fm, _ = split_frontmatter(text)
        for link in wikilinks(text):
            target = resolve_page(all_paths, link)
            if target and target != source:
                add_signal(edges, source, target, "body_wikilink", 1.0)
        for link in list_values(fm, "related"):
            target = resolve_page(all_paths, link)
            if target and target != source:
                add_signal(edges, source, target, "frontmatter_related", 2.0)
        for link in list_values(fm, "sources"):
            target = resolve_page(all_paths, link)
            if target and target != source:
                add_signal(edges, source, target, "source_reference", 0.7)

    for path, page in pages.items():
        prefix = path.split("/", 1)[0] if "/" in path else "root"
        if prefix in ROUTE_WORTHY_PREFIXES and (strip_md(path) in nav_text or Path(strip_md(path)).name in nav_text):
            add_signal(edges, "_meta/navigation", path, "topic_or_moc_route", 1.2)
        aliases = page.get("aliases") or []
        if aliases:
            add_signal(edges, "_meta/aliases", path, "page_aliases", min(2.0, 0.25 * len(aliases)))


def build_inbox_signals(root: Path, title_to_path: dict[str, str], edges: dict[tuple[str, str], EdgeSignal]) -> None:
    query_dir = root / "inbox" / "query-candidates"
    for path in sorted(query_dir.glob("*.md")) if query_dir.exists() else []:
        if path.name == "README.md" or frontmatter_status(read_text(path)) in {"resolved", "closed", "retired"}:
            continue
        text = read_text(path)
        evidence = section(text, "Selected Evidence")
        for line in evidence.splitlines():
            target = source_line_to_page(line, title_to_path)
            if target:
                add_signal(edges, "inbox/query-candidates", target, "selected_for_real_query", 1.5)

    answer_dir = root / "inbox" / "answer-improvements"
    for path in sorted(answer_dir.glob("*.md")) if answer_dir.exists() else []:
        if path.name == "README.md" or frontmatter_status(read_text(path)) in {"resolved", "closed", "retired"}:
            continue
        text = read_text(path)
        quality = 0.0
        match = re.search(r"^quality_score:\s*([0-9.]+)", text, flags=re.M)
        if match:
            try:
                quality = float(match.group(1))
            except ValueError:
                quality = 0.0
        evidence = section(text, "Evidence Seen")
        for line in evidence.splitlines():
            target = source_line_to_page(line, title_to_path)
            if target:
                add_signal(edges, "inbox/answer-improvements", target, "answer_review_evidence", 0.8)
                if quality >= 4.0:
                    add_signal(edges, "inbox/answer-improvements", target, "high_quality_answer_path", 1.2)

    failure_dir = root / "inbox" / "retrieval-failures"
    for path in sorted(failure_dir.glob("*.md")) if failure_dir.exists() else []:
        if path.name == "README.md" or frontmatter_status(read_text(path)) in {"resolved", "closed", "retired"}:
            continue
        text = read_text(path)
        for route in re.findall(r"`([^`]+)`", section(text, "Matched Route Candidates")):
            target = source_line_to_page(route, title_to_path) or route if route.endswith(".md") else f"{route}.md"
            if target in set(title_to_path.values()):
                add_signal(edges, "inbox/retrieval-failures", target, "retrieval_failure_route", -2.0)
        for line in section(text, "Evidence Seen").splitlines():
            target = source_line_to_page(line, title_to_path)
            if target:
                add_signal(edges, "inbox/retrieval-failures", target, "retrieval_failure_seen", -0.7)


def node_scores(pages: dict[str, dict[str, Any]], edges: dict[tuple[str, str], EdgeSignal]) -> list[dict[str, Any]]:
    inbound: dict[str, float] = defaultdict(float)
    outbound: dict[str, float] = defaultdict(float)
    positive_inbound: dict[str, int] = defaultdict(int)
    negative_inbound: dict[str, int] = defaultdict(int)
    signal_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for edge in edges.values():
        outbound[edge.source] += max(edge.score, 0)
        inbound[edge.target] += edge.score
        if edge.score > 0:
            positive_inbound[edge.target] += 1
        if edge.score < 0:
            negative_inbound[edge.target] += 1
        signal_counts[edge.target].update(edge.signals)

    rows = []
    for path, page in pages.items():
        prefix = path.split("/", 1)[0] if "/" in path else "root"
        aliases = page.get("aliases") or []
        related = page.get("related") or []
        score = inbound[path] + min(3.0, 0.2 * len(aliases)) + min(2.0, 0.35 * len(related))
        rows.append(
            {
                "path": path,
                "title": page.get("title", ""),
                "type": page.get("type", ""),
                "score": round(score, 3),
                "inbound_score": round(inbound[path], 3),
                "positive_inbound_edges": positive_inbound[path],
                "negative_inbound_edges": negative_inbound[path],
                "aliases": len(aliases),
                "wikilinks": len(page.get("wikilinks") or []),
                "maintained": prefix in ROUTE_WORTHY_PREFIXES,
                "signals": dict(signal_counts[path].most_common()),
            }
        )
    return sorted(rows, key=lambda row: float(row["score"]), reverse=True)


def recommendations(nodes: list[dict[str, Any]]) -> list[str]:
    out = []
    maintained_nodes = [row for row in nodes if row.get("maintained")]
    for row in sorted(maintained_nodes, key=lambda item: float(item["score"]))[:25]:
        path = str(row["path"])
        if row["positive_inbound_edges"] == 0:
            out.append(f"Add inbound route or related link to `{path}`; current score {row['score']}.")
        elif row["negative_inbound_edges"]:
            out.append(f"Review retrieval failures touching `{path}`; negative edges {row['negative_inbound_edges']}.")
        elif float(row["score"]) < 12.0:
            out.append(f"Strengthen inbound related/MOC links for `{path}`; current score {row['score']}.")
        elif row["aliases"] == 0:
            out.append(f"Consider patient-language aliases for `{path}`.")
        if len(out) >= 12:
            break
    return out


def build(root: Path) -> dict[str, Any]:
    registry = load_json(root / "_meta" / "page-registry.json")
    pages, title_to_path = page_indexes(registry)
    edges: dict[tuple[str, str], EdgeSignal] = {}
    build_structural_edges(root, pages, edges)
    build_inbox_signals(root, title_to_path, edges)
    edge_rows = [
        {
            "source": edge.source,
            "target": edge.target,
            "score": round(edge.score, 3),
            "signals": dict(edge.signals.most_common()),
        }
        for edge in sorted(edges.values(), key=lambda item: item.score, reverse=True)
    ]
    nodes = node_scores(pages, edges)
    maintained_nodes = [row for row in nodes if row.get("maintained")]
    weak_nodes = [row for row in maintained_nodes if float(row["score"]) < 18.0]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "wiki_root": str(root.resolve()),
        "node_count": len(nodes),
        "edge_count": len(edge_rows),
        "top_nodes": nodes[:50],
        "weak_nodes": sorted(weak_nodes, key=lambda row: float(row["score"]))[:50],
        "top_edges": edge_rows[:100],
        "negative_edges": [row for row in edge_rows if row["score"] < 0][:100],
        "recommendations": recommendations(nodes),
    }


def write_outputs(root: Path, payload: dict[str, Any]) -> tuple[Path, Path]:
    meta_path = root / "_meta" / "link-strength.json"
    report_path = root / "reports" / "link-strength-report.md"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    today = date.today().isoformat()
    lines = [
        "---",
        "title: LLM Wiki Link Strength Report",
        "summary: Generated report scoring LLM Wiki page links from related fields, wikilinks, aliases, query-candidate evidence, answer-improvement evidence, and retrieval-failure signals.",
        "type: report",
        f"created: {today}",
        f"updated: {today}",
        "tags: [llm-wiki, graph, link-strength, retrieval]",
        "sources:",
        "  - _meta/page-registry.json",
        "  - inbox/query-candidates/README.md",
        "  - inbox/retrieval-failures/README.md",
        "  - inbox/answer-improvements/README.md",
        "evidence_level: local-practice",
        "clinical_use: workflow",
        "confidence: medium",
        f"last_verified: {today}",
        "status: draft",
        "obsidian_type: report",
        "aliases:",
        "  - link strength report",
        "  - wiki synapse strength",
        "entities:",
        "  - Hermes Agent",
        "  - LLM Wiki",
        "related:",
        "  - reports/wiki-graph-rebuild-audit",
        "  - reports/weekly-wiki-health",
        "  - reports/retrieval-failure-analysis",
        "  - reports/answer-improvement-analysis",
        "owner_agent: hermes",
        "write_policy: hermes-maintained",
        "---",
        "",
        "# LLM Wiki Link Strength Report",
        "",
        f"Generated: {today}",
        "",
        "## Summary",
        "",
        f"- Nodes scored: {payload['node_count']}",
        f"- Edges scored: {payload['edge_count']}",
        f"- Negative edges: {len(payload['negative_edges'])}",
        "",
        "## Scoring Model",
        "",
        "- `frontmatter_related`: +2.0 per related edge.",
        "- `body_wikilink`: +1.0 per body wikilink edge.",
        "- `source_reference`: +0.7 per source edge to another wiki page.",
        "- `topic_or_moc_route`: +1.2 when core navigation routes to the page.",
        "- `page_aliases`: up to +2.0 from patient/search aliases.",
        "- `selected_for_real_query`: +1.5 when a query-candidate selected the page.",
        "- `answer_review_evidence`: +0.8 when an answer-improvement record saw the page.",
        "- `high_quality_answer_path`: +1.2 when reviewer quality score is high.",
        "- `retrieval_failure_route`: -2.0 when a failure points to the page route.",
        "- `retrieval_failure_seen`: -0.7 when failure evidence included the page.",
        "",
        "## Top Strengthened Pages",
        "",
    ]
    for row in payload["top_nodes"][:20]:
        lines.append(f"- `{row['path']}`: score {row['score']}; signals {row['signals']}")
    lines.extend(["", "## Weak Or Underconnected Pages", ""])
    if payload["weak_nodes"]:
        for row in payload["weak_nodes"][:20]:
            lines.append(f"- `{row['path']}`: score {row['score']}; aliases {row['aliases']}; wikilinks {row['wikilinks']}")
    else:
        lines.append("- None")
    lines.extend(["", "## Negative Edges", ""])
    if payload["negative_edges"]:
        for row in payload["negative_edges"][:20]:
            lines.append(f"- `{row['source']}` -> `{row['target']}`: score {row['score']}; signals {row['signals']}")
    else:
        lines.append("- None")
    lines.extend(["", "## Recommended Safe Actions", ""])
    if payload["recommendations"]:
        lines.extend(f"- {item}" for item in payload["recommendations"])
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Use In Retrieval",
            "",
            "Start by using this report as a review queue. Only after repeated runs are stable should scores become retrieval boosts. Keep negative scores as diagnostics first, not hard filters.",
        ]
    )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return meta_path, report_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Score LLM Wiki link strength from graph, inbox, and answer/retrieval feedback signals.")
    parser.add_argument("--wiki", type=Path, default=DEFAULT_WIKI)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = args.wiki.expanduser().resolve()
    payload = build(root)
    outputs = write_outputs(root, payload)
    result = {
        "node_count": payload["node_count"],
        "edge_count": payload["edge_count"],
        "negative_edges": len(payload["negative_edges"]),
        "outputs": [str(path) for path in outputs],
    }
    print(json.dumps(result, ensure_ascii=False) if args.json else f"nodes={result['node_count']} edges={result['edge_count']} negative_edges={result['negative_edges']}")
    if not args.json:
        for path in outputs:
            print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

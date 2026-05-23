#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path


DEFAULT_WIKI = Path("/Users/ander/Documents/hermes-agent/wiki/ada-kdigo-diabetes-wiki")


TOPIC_SEEDS = (
    {
        "slug": "retinopathy-screening",
        "title": "Diabetes Retinopathy Screening And Follow-Up",
        "keywords": ("retinopathy", "retina", "視網膜", "眼底"),
        "suggested_path": "concepts/diabetes-retinopathy-screening.md",
        "search_query": "ADA 2026 diabetes retinopathy screening follow-up recommendations",
    },
    {
        "slug": "foot-care-pad",
        "title": "Diabetes Foot Care And PAD Risk",
        "keywords": ("foot", "pad", "peripheral arterial", "足", "周邊動脈"),
        "suggested_path": "concepts/diabetes-foot-care-pad.md",
        "search_query": "ADA 2026 diabetes foot care peripheral arterial disease screening",
    },
    {
        "slug": "pregnancy-gdm-cgm",
        "title": "Pregnancy Gestational Diabetes And CGM",
        "keywords": ("pregnancy", "gestational", "妊娠", "懷孕", "gdm"),
        "suggested_path": "concepts/diabetes-pregnancy-gdm-cgm.md",
        "search_query": "ADA 2026 pregnancy gestational diabetes CGM recommendations",
    },
    {
        "slug": "hospital-steroid-hyperglycemia",
        "title": "Hospital Steroid Hyperglycemia",
        "keywords": ("hospital", "steroid", "glucocorticoid", "住院", "類固醇"),
        "suggested_path": "concepts/hospital-steroid-hyperglycemia.md",
        "search_query": "ADA 2026 hospital glucocorticoid steroid hyperglycemia management",
    },
    {
        "slug": "masld-mash",
        "title": "Diabetes MASLD And MASH",
        "keywords": ("masld", "mash", "steatotic", "fatty liver", "脂肪肝"),
        "suggested_path": "concepts/diabetes-masld-mash.md",
        "search_query": "ADA 2026 diabetes MASLD MASH GLP-1 pioglitazone recommendation",
    },
    {
        "slug": "lipid-ascvd-targets",
        "title": "Diabetes ASCVD Lipid Targets",
        "keywords": ("ldl", "lipid", "statin", "ascvd", "血脂"),
        "suggested_path": "evidence-cards/ada-2026-lipid-ascvd-recommendation-grades.md",
        "search_query": "ADA 2026 diabetes ASCVD LDL target statin recommendation grade",
    },
    {
        "slug": "bp-ckd-targets",
        "title": "Diabetes CKD Blood Pressure Targets",
        "keywords": ("blood pressure", "bp", "hypertension", "血壓", "高血壓"),
        "suggested_path": "evidence-cards/ada-kdigo-2026-bp-ckd-targets.md",
        "search_query": "ADA 2026 KDIGO diabetes CKD blood pressure target recommendation",
    },
    {
        "slug": "older-adults-frailty",
        "title": "Older Adults Diabetes Frailty And Hypoglycemia",
        "keywords": ("older adults", "frailty", "老年", "長者", "衰弱"),
        "suggested_path": "concepts/older-adults-diabetes-frailty-hypoglycemia.md",
        "search_query": "ADA 2026 older adults diabetes frailty hypoglycemia treatment goals",
    },
    {
        "slug": "glp1-weight-loss-muscle-sarcopenia",
        "title": "GLP-1 Weight Loss Muscle Loss And Sarcopenia",
        "keywords": ("sarcopenia", "smi", "handgrip", "肌少症", "握力"),
        "suggested_path": "concepts/glp1-weight-loss-muscle-sarcopenia.md",
        "search_query": "GLP-1 receptor agonist weight loss lean mass sarcopenia protein resistance training",
    },
)

REVIEW_TERMS = (
    "eGFR",
    "UACR",
    "albuminuria",
    "SGLT2",
    "GLP-1",
    "dialysis",
    "metformin",
    "finerenone",
    "A1C",
    "CGM",
    "sarcopenia",
    "osteoporosis",
)

DEFERRED_TOPICS_PATH = Path("_meta/deferred-topics.md")


@dataclass
class Page:
    path: Path
    rel: str
    frontmatter: str
    body: str
    title: str
    aliases: set[str]
    entities: set[str]
    tags: set[str]


def split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---"):
        return "", text
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, flags=re.S)
    if not match:
        return "", text
    return match.group(1), text[match.end() :]


def field(frontmatter: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}:\s*(.*)$", frontmatter, flags=re.M)
    return match.group(1).strip() if match else ""


def list_field(frontmatter: str, name: str) -> set[str]:
    out: set[str] = set()
    inline = field(frontmatter, name)
    if inline.startswith("[") and inline.endswith("]"):
        out.update(part.strip().strip("'\"") for part in inline[1:-1].split(",") if part.strip())
    block = re.search(rf"^{re.escape(name)}:\s*\n((?:\s+- .+\n?)+)", frontmatter, flags=re.M)
    if block:
        out.update(line.split("-", 1)[1].strip().strip("'\"") for line in block.group(1).splitlines() if "-" in line)
    return {item.lower() for item in out if item}


def load_pages(root: Path) -> list[Page]:
    pages: list[Page] = []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(".obsidian/") or path.name.startswith("Icon"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        fm, body = split_frontmatter(text)
        title = field(fm, "title") or path.stem.replace("-", " ")
        pages.append(
            Page(
                path=path,
                rel=rel,
                frontmatter=fm,
                body=body,
                title=title,
                aliases=list_field(fm, "aliases"),
                entities=list_field(fm, "entities"),
                tags=list_field(fm, "tags"),
            )
        )
    return pages


def load_deferred_topic_slugs(root: Path) -> set[str]:
    path = root / DEFERRED_TOPICS_PATH
    if not path.exists():
        return set()
    text = path.read_text(encoding="utf-8", errors="ignore")
    slugs: set[str] = set()
    for match in re.finditer(r"^\s*(?:-\s*)?slug:\s*`?([a-z0-9-]+)`?\s*$", text, flags=re.M):
        slugs.add(match.group(1).strip())
    for match in re.finditer(r"`([a-z0-9-]+)`", text):
        slugs.add(match.group(1).strip())
    return slugs


def tokenize(text: str) -> set[str]:
    tokens = set(re.findall(r"[a-zA-Z][a-zA-Z0-9+\-.]*|[\u4e00-\u9fff]{2,4}", text.lower()))
    stop = {"guideline", "diabetes", "patient", "clinical", "source", "wiki", "page", "with", "and", "the"}
    return {token for token in tokens if token not in stop and len(token) > 1}


def duplicate_candidates(pages: list[Page]) -> list[str]:
    candidates: list[tuple[float, str]] = []
    eligible_prefixes = (
        "concepts/",
        "drugs/",
        "comparisons/",
        "evidence-cards/",
        "claims/",
        "guidelines/",
        "teaching/",
        "patient-education/",
        "queries/",
    )
    eligible = [p for p in pages if p.rel.startswith(eligible_prefixes)]
    signatures = {
        p.rel: tokenize(" ".join([p.title, *p.aliases, *p.entities, *p.tags]))
        for p in eligible
    }
    for i, left in enumerate(eligible):
        for right in eligible[i + 1 :]:
            a = signatures[left.rel]
            b = signatures[right.rel]
            if not a or not b:
                continue
            overlap = len(a & b) / max(1, min(len(a), len(b)))
            if overlap >= 0.42:
                candidates.append((overlap, f"{left.rel} <> {right.rel} ({overlap:.2f})"))
    return [item for _, item in sorted(candidates, reverse=True)[:25]]


def topic_gaps(pages: list[Page], deferred_slugs: set[str] | None = None) -> list[str]:
    deferred_slugs = deferred_slugs or set()
    searchable = "\n".join(
        f"{p.rel}\n{p.title}\n{' '.join(p.aliases)}\n{' '.join(p.entities)}\n{' '.join(p.tags)}"
        for p in pages
        if not p.rel.startswith(("raw/", "reports/", "inbox/"))
    ).lower()
    gaps = []
    for seed in TOPIC_SEEDS:
        if seed["slug"] in deferred_slugs:
            continue
        target = seed["suggested_path"].lower()
        if target in searchable:
            continue
        if not any(keyword.lower() in searchable for keyword in seed["keywords"]):
            gaps.append(
                f"{seed['title']} -> suggested `{seed['suggested_path']}`; search: {seed['search_query']}"
            )
            continue
        slug_pattern = re.escape(seed["slug"]).replace(r"\-", "[- ]")
        if not re.search(rf"\[\[.*{slug_pattern}.*\]\]", searchable):
            gaps.append(
                f"{seed['title']} may be under-routed -> suggested `{seed['suggested_path']}`; search: {seed['search_query']}"
            )
    return gaps


def consistency_review_candidates(pages: list[Page]) -> list[str]:
    def clean_snippet(line: str) -> str:
        without_links = re.sub(r"\[\[([^\]]+)\]\]", r"`\1`", line)
        return re.sub(r"\s+", " ", without_links.strip())[:180]

    candidates = []
    for term in REVIEW_TERMS:
        hits = []
        term_re = re.compile(re.escape(term), flags=re.I)
        threshold_re = re.compile(r"(?:eGFR|UACR|A1C|HbA1c|LDL|BP|SMI|handgrip|握力|肌肉).*?(?:[<>≥≤=]|grade|recommendation|建議|等級|kg|mg/g|mL/min|%)", flags=re.I)
        for page in pages:
            if page.rel.startswith(("raw/", "reports/", "inbox/")):
                continue
            if not term_re.search(page.frontmatter + "\n" + page.body):
                continue
            lines = []
            for line in page.body.splitlines():
                if term_re.search(line) and threshold_re.search(line):
                    lines.append(clean_snippet(line))
            if lines:
                hits.append(f"{page.rel}: {lines[0]}")
        if len(hits) >= 2:
            candidates.append(f"{term}: review {len(hits)} pages for threshold/grade consistency")
            candidates.extend(f"  - {hit}" for hit in hits[:5])
    return candidates[:80]


def synthetic_question_candidates(pages: list[Page]) -> list[str]:
    candidates = []
    for page in pages:
        if page.rel.startswith(("raw/", "reports/", "inbox/", "docs/", "_meta/")):
            continue
        terms = list(page.aliases or page.entities or page.tags)[:4]
        if not terms:
            continue
        candidates.append(f"- `{page.rel}`: 請根據 {page.title} 整理 {'、'.join(terms)} 的臨床重點與需要查證處。")
    return candidates[:40]


def write_research_requests(root: Path, gaps: list[str], limit: int) -> list[str]:
    out_dir = root / "inbox" / "research-requests"
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    today = date.today().isoformat()
    existing_text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in out_dir.glob("*.md"))
    for gap in gaps[:limit]:
        title = gap.split(" -> ", 1)[0].replace(" may be under-routed", "")
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:70]
        if title in existing_text:
            continue
        path = out_dir / f"{today}-self-audit-{slug}.md"
        path.write_text(
            "\n".join(
                [
                    "---",
                    f"title: Research Request - {title}",
                    "type: research-request",
                    f"created: {today}",
                    f"updated: {today}",
                    "tags: [self-audit, research-request, llm-wiki]",
                    "sources:",
                    "  - reports/wiki-self-improvement-audit.md",
                    "evidence_level: local-practice",
                    "clinical_use: workflow",
                    "confidence: uncertain",
                    f"last_verified: {today}",
                    "status: open",
                    "obsidian_type: report",
                    "aliases: []",
                    "entities: [Hermes Agent]",
                    "owner_agent: hermes",
                    "write_policy: hermes-maintained",
                    "---",
                    "",
                    f"# {title}",
                    "",
                    "## Trigger",
                    "",
                    gap,
                    "",
                    "## Task",
                    "",
                    "Search raw ADA/KDIGO sources first, then current external medical literature if needed. Propose a page, aliases, sources, and smoke-test terms. Do not write unsourced clinical claims.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        written.append(path.relative_to(root).as_posix())
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate proactive LLM Wiki self-improvement audit.")
    parser.add_argument("--wiki", type=Path, default=DEFAULT_WIKI)
    parser.add_argument("--write-requests", action="store_true")
    parser.add_argument("--request-limit", type=int, default=5)
    args = parser.parse_args()

    root = args.wiki
    pages = load_pages(root)
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)

    duplicates = duplicate_candidates(pages)
    deferred_slugs = load_deferred_topic_slugs(root)
    gaps = topic_gaps(pages, deferred_slugs)
    consistency = consistency_review_candidates(pages)
    synthetic = synthetic_question_candidates(pages)
    written = write_research_requests(root, gaps, args.request_limit) if args.write_requests else []

    today = date.today().isoformat()
    lines = [
        "---",
        "title: Wiki Self-Improvement Audit",
        "summary: Generated proactive lint report for duplicate concepts, topic gaps, consistency review candidates, and synthetic QA seeds.",
        "type: report",
        f"created: {today}",
        f"updated: {today}",
        "tags: [llm-wiki, self-improvement, audit]",
        "sources:",
        "  - _meta/page-registry.json",
        "  - _meta/claim-registry.json",
        "evidence_level: local-practice",
        "clinical_use: workflow",
        "confidence: high",
        f"last_verified: {today}",
        "status: active",
        "obsidian_type: report",
        "aliases:",
        "  - wiki self-improvement audit",
        "entities:",
        "  - Hermes Agent",
        "related:",
        "  - reports/weekly-wiki-health",
        "  - reports/source-freshness-watch",
        "  - _meta/deferred-topics",
        "owner_agent: hermes",
        "write_policy: hermes-maintained",
        "---",
        "",
        "# Wiki Self-Improvement Audit",
        "",
        f"Generated: {today}",
        "",
        "## Purpose",
        "",
        "This report is a proactive lint layer for the LLM Wiki. It is designed to find work before a LINE user asks a failing question.",
        "",
        "## Summary",
        "",
        f"- Pages scanned: {len(pages)}",
        f"- Duplicate/merge candidates: {len(duplicates)}",
        f"- Topic gaps or under-routed topics: {len(gaps)}",
        f"- Deferred topic seeds skipped: {len(deferred_slugs)}",
        f"- Consistency review candidates: {len(consistency)}",
        f"- Synthetic QA seed questions: {len(synthetic)}",
        f"- Research requests written: {len(written)}",
        "",
        "## Duplicate Or Merge Candidates",
        "",
    ]
    lines.extend(f"- {item}" for item in duplicates[:40]) if duplicates else lines.append("- None")
    lines.extend(["", "## Topic Gaps Or Under-Routed Topics", ""])
    lines.extend(f"- {item}" for item in gaps) if gaps else lines.append("- None")
    lines.extend(["", "## Consistency Review Candidates", ""])
    lines.extend(f"- {item}" if not item.startswith("  -") else item for item in consistency) if consistency else lines.append("- None")
    lines.extend(["", "## Synthetic QA Seed Questions", ""])
    lines.extend(synthetic) if synthetic else lines.append("- None")
    lines.extend(["", "## Research Requests Written", ""])
    lines.extend(f"- [[../{item[:-3]}]]" for item in written) if written else lines.append("- None")
    lines.extend(
        [
            "",
            "## Operating Rule",
            "",
            "- Code-based findings are candidates, not clinical truth.",
            "- Hermes should verify threshold, grade, and medication claims against raw sources before editing canonical clinical pages.",
            "- Safe autonomous edits: aliases, topic-map routes, smoke-test additions, and research-request creation.",
            "- Human review is still preferred before changing exact clinical recommendations.",
            "",
            "## Related Pages",
            "",
            "- [[../reports/weekly-wiki-health]]",
            "- [[../reports/source-freshness-watch]]",
        ]
    )

    out = reports / "wiki-self-improvement-audit.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

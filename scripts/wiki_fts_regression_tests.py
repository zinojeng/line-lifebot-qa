#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import wiki_fts_search
from knowledge import KnowledgeChunk, chunk_excluded_for_query, domain_adjustment


DEFAULT_WIKI = Path("/Users/ander/Documents/hermes-agent/wiki/ada-kdigo-diabetes-wiki")


@dataclass(frozen=True)
class FtsRegressionCase:
    name: str
    query: str
    expected_terms: tuple[str, ...]
    forbidden_terms: tuple[str, ...] = ()
    forbidden_scope: int = 10
    expected_top_path_prefix: str = ""


CASES = (
    FtsRegressionCase(
        name="type1-universal-screening-routes-section2",
        query="第一型糖尿病的病患，是否適合用普篩的方式來找出來呢？",
        expected_terms=("type 1 diabetes screening", "2.7", "autoantibody", "islet"),
        forbidden_terms=("masld", "mash", "retinopathy-foot-pad", "bone-glp1-muscle"),
        forbidden_scope=2,
        expected_top_path_prefix="queries/type-1-diabetes-screening-line-questions.md",
    ),
    FtsRegressionCase(
        name="retinopathy-evidence-grade-no-ckd-default",
        query="嚴重眼病變治療 證據等級是？",
        expected_terms=("section 12", "12.9", "12.12", "anti-vegf", "grade"),
        forbidden_terms=("ckd-cardiorenal", "ada-kdigo-2026-ckd-cardiorenal"),
    ),
    FtsRegressionCase(
        name="neuropathy-medication-evidence-grade-no-ckd-default",
        query="糖尿病神經病變藥物的證據等級是？",
        expected_terms=("section 12", "12.22", "gabapentinoid", "snri", "grade"),
        forbidden_terms=("ckd-cardiorenal", "ada-kdigo-2026-ckd-cardiorenal"),
    ),
    FtsRegressionCase(
        name="masld-mash-evidence-grade-no-ckd-default",
        query="糖尿病 MASH 建議等級",
        expected_terms=("ada 2026 section 4", "4.27a", "fib-4", "mash", "grade"),
        forbidden_terms=("ckd-cardiorenal", "finerenone", "uacr", "egfr"),
    ),
    FtsRegressionCase(
        name="ckd-evidence-grade-still-routes-ckd",
        query="58歲第二型糖尿病 eGFR 42 UACR 380，ADA/KDIGO 哪些建議是 strong recommendation，哪些證據等級較低？",
        expected_terms=("ckd-cardiorenal", "11.7a", "4.3.1", "grade c", "lower-certainty"),
    ),
    FtsRegressionCase(
        name="generic-evidence-grade-does-not-ckd-lock",
        query="ADA 2026 哪些建議等級較低？",
        expected_terms=("evidence-grade-router", "claim", "grade"),
    ),
    FtsRegressionCase(
        name="taiwan-implementation-zh-alias-no-ckd-default",
        query="台灣 ADA 2026 臨床影響",
        expected_terms=("ada-2025-vs-2026-taiwan-impact", "taiwan clinical impact"),
        forbidden_terms=("ada-kdigo-2026-bp-ckd-targets", "ckd-cardiorenal"),
        forbidden_scope=3,
        expected_top_path_prefix="comparisons/ada-2025-vs-2026-taiwan-impact.md",
    ),
    FtsRegressionCase(
        name="taiwan-practice-zh-alias-no-ckd-default",
        query="ADA 2026 台灣實務影響",
        expected_terms=("ada-2025-vs-2026-taiwan-impact", "taiwan clinical impact"),
        forbidden_terms=("ada-kdigo-2026-bp-ckd-targets", "ckd-cardiorenal"),
        forbidden_scope=3,
        expected_top_path_prefix="comparisons/ada-2025-vs-2026-taiwan-impact.md",
    ),
    FtsRegressionCase(
        name="ada-2026-short-alias-routes-alias-page",
        query="ADA 2026 alias page",
        expected_terms=("guidelines/ada2026", "routing use"),
        forbidden_terms=("ada-kdigo-2026-bp-ckd-targets",),
        forbidden_scope=3,
        expected_top_path_prefix="guidelines/ada2026.md",
    ),
)


def hit_text(hits: list[wiki_fts_search.Hit], limit: int) -> str:
    parts: list[str] = []
    for hit in hits[:limit]:
        parts.extend([hit.path, hit.title, hit.section, hit.page_type, hit.excerpt])
    return " ".join(parts).lower()


def run_case(case: FtsRegressionCase, db: Path, limit: int) -> tuple[bool, str]:
    hits = wiki_fts_search.search(db, case.query, limit=limit)
    text = hit_text(hits, limit)
    matched = any(term.lower() in text for term in case.expected_terms)
    forbidden_text = hit_text(hits, case.forbidden_scope)
    forbidden = [term for term in case.forbidden_terms if term.lower() in forbidden_text]
    top = hits[0].path if hits else "-"
    top_ok = not case.expected_top_path_prefix or top.startswith(case.expected_top_path_prefix)
    ok = matched and not forbidden and top_ok
    return ok, (
        f"{'PASS' if ok else 'FAIL'}\t{case.name}\t"
        f"top={top}\tmatched={matched}\ttop_ok={top_ok}\tforbidden={','.join(forbidden) or '-'}"
    )


def run_chunk_exclusion_tests() -> list[str]:
    failures: list[str] = []
    liver_chunk = KnowledgeChunk(
        source="claims/ada-2026-masld-mash-claims.md",
        source_label="ADA 2026 MASLD MASH Claim Registry",
        title="ADA 2026 MASLD MASH Claim Registry",
        section="Claim Cards",
        chunk_type="llm_wiki_page",
        text="ADA 4.32a Grade B metabolic surgery for MASH. The page notes cardiometabolic comorbidity and kidney risk factors in diabetes.",
        parent_text="MASLD MASH FIB-4 liver fibrosis GLP-1 RA pioglitazone tirzepatide resmetirom.",
        metadata=("claim", "masld", "mash"),
        tokens=(),
    )
    query = "糖尿病 MASH 建議等級"
    if chunk_excluded_for_query(query, liver_chunk):
        failures.append("FAIL\tmasld-liver-chunk-with-kidney-word-not-excluded")
    if domain_adjustment(query, liver_chunk) <= 1.0:
        failures.append("FAIL\tmasld-4-32a-domain-boost")
    ckd_chunk = KnowledgeChunk(
        source="claims/ada-kdigo-2026-ckd-cardiorenal-claims.md",
        source_label="ADA KDIGO CKD Cardiorenal Claims",
        title="ADA KDIGO CKD Cardiorenal Claim Registry",
        section="Claim Cards",
        chunk_type="llm_wiki_page",
        text="CKD cardiorenal claim_id finerenone eGFR UACR albuminuria.",
        parent_text="",
        metadata=("claim", "ckd"),
        tokens=(),
    )
    if not chunk_excluded_for_query(query, ckd_chunk):
        failures.append("FAIL\tmasld-query-excludes-ckd-cardiorenal-claim")
    if not wiki_fts_search.should_merge_fallback("alias page for ADA 2026"):
        failures.append("FAIL\tworkflow-alias-query-enables-fallback")
    if wiki_fts_search.should_merge_fallback("recommended route of administration for insulin"):
        failures.append("FAIL\tadministration-route-does-not-enable-workflow-fallback")
    if wiki_fts_search.should_merge_fallback("preferred route to administer insulin in pregnancy"):
        failures.append("FAIL\tclinical-route-to-does-not-enable-workflow-fallback")
    if not wiki_fts_search.should_merge_fallback("routes to alias page for ADA 2026"):
        failures.append("FAIL\tworkflow-routes-to-alias-enables-fallback")
    if not wiki_fts_search.should_merge_fallback("ADA 2026 evidence grade B"):
        failures.append("FAIL\tevidence-grade-still-enables-fallback")
    if wiki_fts_search.should_apply_exact_phrase_boost("short"):
        failures.append("FAIL\texact-phrase-short-query-not-boosted")
    if not wiki_fts_search.should_apply_exact_phrase_boost("台灣 ada 2026 臨床影響"):
        failures.append("FAIL\texact-phrase-cjk-alias-boosted")
    if not wiki_fts_search.should_apply_exact_phrase_boost("ada 2026 alias page"):
        failures.append("FAIL\texact-phrase-ascii-multitoken-boosted")
    section12_crossref_chunk = KnowledgeChunk(
        source="evidence-cards/ada-2026-section-12-retinopathy-neuropathy-foot-pad-recommendation-grades.md",
        source_label="ADA 2026 Section 12 Retinopathy Neuropathy Foot PAD Recommendation Grades",
        title="ADA 2026 Section 12 Retinopathy Neuropathy Foot PAD Recommendation Grades",
        section="Answering Notes",
        chunk_type="llm_wiki_page",
        text="For cross-cutting questions, mention claims/ada-kdigo-2026-ckd-cardiorenal-claims only when kidney context is explicit.",
        parent_text="Section 12 retinopathy neuropathy foot PAD recommendation grades.",
        metadata=("evidence-card", "section12"),
        tokens=(),
    )
    if chunk_excluded_for_query("嚴重眼病變治療 證據等級是？", section12_crossref_chunk):
        failures.append("FAIL\tsection12-crossref-body-ckd-path-not-excluded")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Local SQLite FTS regression tests for LLM Wiki evidence-grade routing.")
    parser.add_argument("--wiki", type=Path, default=DEFAULT_WIKI)
    parser.add_argument("--db", type=Path, default=DEFAULT_WIKI / "_meta" / "wiki-search.sqlite3")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()

    if args.rebuild or not args.db.exists():
        wiki_fts_search.rebuild(args.wiki, args.db)

    failures: list[str] = []
    for case in CASES:
        ok, message = run_case(case, args.db, args.limit)
        print(message)
        if not ok:
            failures.append(message)
    chunk_failures = run_chunk_exclusion_tests()
    for failure in chunk_failures:
        print(failure)
    failures.extend(chunk_failures)
    if failures:
        print("\nFailures:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

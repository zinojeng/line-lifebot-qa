#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_WIKI = Path("/Users/ander/Documents/hermes-agent/wiki/ada-kdigo-diabetes-wiki")


@dataclass(frozen=True)
class RegressionCase:
    name: str
    query: str
    expected_terms: tuple[str, ...]
    forbidden_terms: tuple[str, ...] = ("片段", "AACE")
    expected_mode: str = "fast_path"
    forbidden_scope: int = 10


BUILTIN_CASES = (
    RegressionCase(
        "ckd-evidence-grade-follow-up",
        "58歲第二型糖尿病 eGFR 42 UACR 380，ADA/KDIGO 哪些建議是 strong recommendation，哪些證據等級較低？",
        ("claim registry", "11.7a", "4.3.1", "grade c", "lower-certainty"),
    ),
    RegressionCase(
        "bone-health-not-fragment-answer",
        "糖尿病與骨質疏鬆，治療是否與一般人不同？",
        ("osteoporosis", "bone health", "fracture", "frax"),
    ),
    RegressionCase(
        "glp1-muscle-sarcopenia",
        "我54歲使用GLP1減重後，SMI降低、手握力和腿沒力氣，我會不會肌少症？",
        ("sarcopenia", "smi", "handgrip", "chair stand"),
    ),
    RegressionCase(
        "gdm-metformin-evidence",
        "Metformin in GDM evidence",
        ("15.17", "15.21", "metformin", "glyburide", "insulin"),
        forbidden_terms=("片段", "AACE", "no loaded guideline evidence", "沒有載入", "無相關指南", "禁用", "完全不能使用", "absolutely forbidden"),
    ),
    RegressionCase(
        "gdm-metformin-zh",
        "妊娠糖尿病 metformin 證據如何？",
        ("15.17", "15.21", "metformin", "glyburide", "insulin"),
        forbidden_terms=("片段", "AACE", "no loaded guideline evidence", "沒有載入", "無相關指南", "禁用", "完全不能使用", "absolutely forbidden"),
    ),
    RegressionCase(
        "gdm-metformin-evidence-grade-zh",
        "妊娠糖尿病 metformin 的證據等級是什麼？",
        ("15.17", "15.21", "grade a", "grade b", "metformin"),
        forbidden_terms=("片段", "AACE", "no loaded guideline evidence", "沒有載入", "無相關指南", "禁用", "完全不能使用", "absolutely forbidden"),
    ),
    RegressionCase(
        "type1-universal-screening-zh",
        "第一型糖尿病的病患，是否適合用普篩的方式來找出來呢？",
        ("type 1 diabetes", "2.7", "autoantibody", "islet"),
        forbidden_terms=("片段", "AACE", "no loaded guideline evidence", "沒有載入", "無相關指南", "目前快速問答暫時無法回覆", "MASLD", "MASH"),
    ),
    RegressionCase(
        "retinopathy-treatment-evidence-grade",
        "嚴重眼病變治療 證據等級是？",
        ("section 12", "12.9", "12.12", "grade a", "anti-vegf", "retinopathy"),
        forbidden_terms=("片段", "AACE", "no loaded guideline evidence", "沒有載入", "無相關指南", "ada-kdigo-2026-ckd-cardiorenal-claim-registry", "ckd-cardiorenal-claims", "ckd-cardiorenal-recommendation-grades"),
    ),
    RegressionCase(
        "neuropathy-medication-evidence-grade",
        "糖尿病神經病變藥物的證據等級是？",
        ("section 12", "12.22", "grade a", "gabapentinoid", "snri", "opioid"),
        forbidden_terms=("片段", "AACE", "no loaded guideline evidence", "沒有載入", "無相關指南", "ada-kdigo-2026-ckd-cardiorenal-claim-registry", "ckd-cardiorenal-claims", "ckd-cardiorenal-recommendation-grades"),
    ),
    RegressionCase(
        "masld-mash-evidence-grade-no-ckd-default",
        "糖尿病 MASH 建議等級",
        ("ada 2026 section 4", "4.27a", "fib-4", "glp-1", "mash"),
        forbidden_terms=("片段", "AACE", "no loaded guideline evidence", "沒有載入", "無相關指南", "ada-kdigo-2026-ckd-cardiorenal-claim-registry", "ckd-cardiorenal-claims", "ckd-cardiorenal-recommendation-grades", "finerenone", "uacr", "egfr"),
    ),
)


def fetch_debug(base_url: str, query: str, token: str, timeout: int) -> dict:
    url = f"{base_url.rstrip('/')}/debug/search?{urlencode({'q': query})}"
    headers = {"x-debug-token": token} if token else {}
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def haystack(payload: dict, limit: int = 10) -> str:
    parts = [payload.get("retrieval_mode", ""), payload.get("retrieval_query", "")]
    for hit in payload.get("candidates", [])[:limit]:
        parts.extend(
            [
                hit.get("source", ""),
                hit.get("source_label", ""),
                hit.get("title", ""),
                hit.get("section", ""),
                hit.get("chunk_type", ""),
                hit.get("excerpt", ""),
                " ".join(hit.get("metadata", [])),
            ]
        )
    return " ".join(str(part) for part in parts).lower()


def load_generated_cases(root: Path, max_cases: int) -> list[RegressionCase]:
    path = root / "evals" / "synthetic-qa-cases.jsonl"
    if not path.exists():
        return []
    cases: list[RegressionCase] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        expected = tuple(str(term).lower() for term in payload.get("expected_terms", [])[:5])
        query = str(payload.get("query", "")).strip()
        name = str(payload.get("name", "")).strip()
        if not query or not name or not expected:
            continue
        cases.append(RegressionCase(name=name, query=query, expected_terms=expected))
        if len(cases) >= max_cases:
            break
    return cases


def run_case(base_url: str, case: RegressionCase, token: str, timeout: int) -> tuple[bool, str]:
    started = time.monotonic()
    payload = fetch_debug(base_url, case.query, token=token, timeout=timeout)
    elapsed = round((time.monotonic() - started) * 1000, 1)
    mode = payload.get("retrieval_mode", "")
    text = haystack(payload)
    matched = any(term.lower() in text for term in case.expected_terms)
    forbidden_text = haystack(payload, limit=case.forbidden_scope)
    forbidden = [term for term in case.forbidden_terms if term.lower() in forbidden_text]
    ok = mode == case.expected_mode and matched and not forbidden
    message = (
        f"{'PASS' if ok else 'FAIL'}\t{case.name}\tmode={mode}\t"
        f"elapsed_ms={payload.get('elapsed_ms')}\ttotal_ms={elapsed}\t"
        f"matched={matched}\tforbidden={','.join(forbidden) or '-'}"
    )
    return ok, message


def main() -> int:
    parser = argparse.ArgumentParser(description="Regression checks for LINE QA retrieval quality.")
    parser.add_argument("--base-url", default="https://linebotqa.zeabur.app")
    parser.add_argument("--debug-token", default="")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--wiki", type=Path, default=DEFAULT_WIKI)
    parser.add_argument("--include-generated", action="store_true")
    parser.add_argument("--generated-limit", type=int, default=12)
    args = parser.parse_args()

    cases = list(BUILTIN_CASES)
    if args.include_generated:
        cases.extend(load_generated_cases(args.wiki, args.generated_limit))

    failures: list[str] = []
    for case in cases:
        try:
            ok, message = run_case(args.base_url, case, args.debug_token, args.timeout)
        except Exception as exc:
            ok = False
            message = f"FAIL\t{case.name}\trequest failed: {type(exc).__name__}: {exc}"
        print(message)
        if not ok:
            failures.append(message)

    if failures:
        print("\nFailures:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

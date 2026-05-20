#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class SmokeCase:
    name: str
    query: str
    expect_any: tuple[str, ...]
    expect_mode: str = "fast_path"


CASES = (
    SmokeCase(
        "sglt2i-egfr-under-20",
        "排糖藥 SGLT2i eGFR 小於 20 還沒洗腎可以繼續嗎？",
        ("sglt2i", "egfr", "under 20", "11.11a", "ckd"),
    ),
    SmokeCase(
        "glp1-dialysis",
        "洗腎病人可以用 GLP-1RA 嗎？ADA 2026 和 KDIGO 2026 怎麼看？",
        ("glp-1", "glp1", "dialysis", "11.11b", "kidney failure"),
    ),
    SmokeCase(
        "cgm-indications",
        "糖尿病的新科技連續血糖監測 CGM 適合哪些病人？",
        ("cgm", "continuous glucose", "diabetes technology", "time in range"),
    ),
    SmokeCase(
        "ada-kdigo-ckd-crosswalk",
        "ADA 2026 和 KDIGO 2026 對糖尿病 CKD 用藥差異是什麼？",
        ("ada 2026", "kdigo 2026", "crosswalk", "ckd", "sglt2"),
    ),
    SmokeCase(
        "uacr-albuminuria",
        "糖尿病腎病變 UACR 白蛋白尿和 eGFR 要怎麼做風險分層？",
        ("uacr", "albuminuria", "egfr", "risk stratification"),
    ),
    SmokeCase(
        "finerenone",
        "finerenone 在糖尿病 CKD 什麼情境會被考慮？",
        ("finerenone", "ckd", "albuminuria", "kdigo"),
    ),
    SmokeCase(
        "metformin-ckd",
        "metformin 遇到 CKD eGFR 下降時 guideline 重點是什麼？",
        ("metformin", "egfr", "ckd"),
    ),
    SmokeCase(
        "a1c-reliability-ckd",
        "腎功能很差或洗腎時 A1C 可靠嗎？KDIGO 有沒有提 CGM？",
        ("a1c", "cgm", "dialysis", "glycemic monitoring"),
    ),
    SmokeCase(
        "hypoglycemia-advanced-ckd",
        "advanced CKD 糖尿病低血糖風險要注意什麼？",
        ("hypoglycemia", "ckd", "kidney"),
    ),
    SmokeCase(
        "older-adults",
        "ADA 2026 older adults 糖尿病治療目標和低血糖要怎麼教醫學生？",
        ("older adults", "hypoglycemia", "ada"),
    ),
    SmokeCase(
        "pregnancy",
        "ADA 2026 pregnancy gestational diabetes CGM 有哪些重點？",
        ("pregnancy", "gestational", "cgm", "ada"),
    ),
    SmokeCase(
        "hospital-steroid",
        "住院使用 steroid 造成高血糖 ADA 2026 要怎麼找章節？",
        ("hospital", "steroid", "glucocorticoid", "hyperglycemia"),
    ),
    SmokeCase(
        "organ-centric",
        "怎麼跟醫學生解釋 organ-centric diabetes care？",
        ("organ-centric", "heart", "kidney", "teaching"),
    ),
    SmokeCase(
        "ada-2025-2026",
        "ADA 2025 vs 2026 CKD 章節變化和 Taiwan impact 有什麼重點？",
        ("2025", "2026", "taiwan", "ckd"),
    ),
    SmokeCase(
        "bp-target",
        "糖尿病 CKD blood pressure target ADA 2026 怎麼查？",
        ("blood pressure", "ckd", "ada"),
    ),
    SmokeCase(
        "lipid-target",
        "糖尿病 ASCVD LDL 目標 ADA 2026 重點是什麼？",
        ("ldl", "ascvd", "lipid", "ada"),
    ),
    SmokeCase(
        "masld",
        "糖尿病合併 MASLD MASH 指引重點要去哪裡找？",
        ("masld", "mash", "liver", "diabetes"),
    ),
    SmokeCase(
        "bone-health-osteoporosis",
        "糖尿病與骨質疏鬆，治療是否與一般人不同？",
        ("osteoporosis", "bone health", "fracture", "t-score", "frax"),
    ),
    SmokeCase(
        "glp1-muscle-sarcopenia",
        "我54歲使用GLP1減重後，肌肉質量指數 SMI 降低，覺得手握力和腿沒力氣，我會不會肌少症？",
        ("sarcopenia", "smi", "handgrip", "chair stand", "muscle"),
    ),
    SmokeCase(
        "foot-care",
        "糖尿病足部照護和 PAD 風險 ADA 2026 怎麼整理？",
        ("foot", "pad", "ada"),
    ),
    SmokeCase(
        "retinopathy",
        "糖尿病視網膜病變 retinopathy ADA 2026 追蹤重點？",
        ("retinopathy", "ada", "screening"),
    ),
    SmokeCase(
        "medical-student-brief",
        "請用 ADA KDIGO 2026 幫醫學生整理糖尿病 CKD 20 分鐘教學重點",
        ("medical student", "teaching", "ada", "kdigo"),
    ),
    SmokeCase(
        "evidence-grade-ckd-followup",
        "58歲第二型糖尿病 eGFR 42 UACR 380 冠狀動脈疾病 metformin basal insulin，ADA 2026 KDIGO 2026 哪些建議是 strong recommendation，哪些證據等級較低？",
        ("11.7a", "4.3.1", "1a", "grade a", "lower-certainty"),
    ),
)


def fetch_debug(base_url: str, query: str, token: str = "", timeout: int = 60) -> dict:
    url = f"{base_url.rstrip('/')}/debug/search?{urlencode({'q': query})}"
    headers = {"x-debug-token": token} if token else {}
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def haystack(payload: dict) -> str:
    parts = [
        payload.get("retrieval_mode", ""),
        payload.get("retrieval_query", ""),
    ]
    for hit in payload.get("candidates", [])[:8]:
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


def run(base_url: str, token: str = "", sleep_seconds: float = 0.0) -> int:
    failures: list[str] = []
    for case in CASES:
        started = time.monotonic()
        try:
            payload = fetch_debug(base_url, case.query, token=token)
        except Exception as exc:
            failures.append(f"{case.name}: request failed: {type(exc).__name__}: {exc}")
            continue
        elapsed = round((time.monotonic() - started) * 1000, 1)
        mode = payload.get("retrieval_mode", "")
        text = haystack(payload)
        matched = any(term.lower() in text for term in case.expect_any)
        status = "PASS" if mode == case.expect_mode and matched else "FAIL"
        print(
            f"{status}\t{case.name}\tmode={mode}\telapsed_ms={payload.get('elapsed_ms')}"
            f"\tretrieval_ms={payload.get('retrieval_elapsed_ms')}\ttotal_ms={elapsed}"
        )
        if status == "FAIL":
            failures.append(
                f"{case.name}: mode={mode!r}, expected={case.expect_mode!r}, matched={matched}, terms={case.expect_any}"
            )
        if sleep_seconds:
            time.sleep(sleep_seconds)
    if failures:
        print("\nFailures:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://linebotqa.zeabur.app")
    parser.add_argument("--debug-token", default="")
    parser.add_argument("--sleep", type=float, default=0.0)
    args = parser.parse_args()
    return run(args.base_url, token=args.debug_token, sleep_seconds=args.sleep)


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import re


REQUIRED_SECTION12_WIKI_FILES = (
    "mocs/evidence-grade-router-moc.md",
    "evidence-cards/ada-2026-section-12-retinopathy-neuropathy-foot-pad-recommendation-grades.md",
    "claims/ada-2026-retinopathy-foot-pad-claims.md",
)
CKD_CARDIORENAL_CLAIMS_PATH = "claims/ada-kdigo-2026-ckd-cardiorenal-claims"
CKD_CARDIORENAL_EVIDENCE_CARD_PATH = "evidence-cards/ada-kdigo-2026-ckd-cardiorenal-recommendation-grades"
CKD_CARDIORENAL_CLAIM_REGISTRY_TITLE = "ada-kdigo-2026-ckd-cardiorenal-claim-registry"

SECTION12_REQUIRED_TERMS = (
    "12.9",
    "12.10",
    "12.11",
    "12.12",
    "12.13",
    "12.20",
    "12.21",
    "12.22",
    "12.23",
    "12.24",
    "12.25",
    "12.26",
    "12.27",
    "12.28",
    "12.29",
    "Grade A",
    "anti-VEGF",
    "gabapentinoids",
)


def strip_md_suffix(path: str) -> str:
    return path[:-3] if path.endswith(".md") else path


SECTION12_ROUTER_MOC_PATH = strip_md_suffix(REQUIRED_SECTION12_WIKI_FILES[0])
SECTION12_EVIDENCE_CARD_PATH = strip_md_suffix(REQUIRED_SECTION12_WIKI_FILES[1])
SECTION12_CLAIM_REGISTRY_PATH = strip_md_suffix(REQUIRED_SECTION12_WIKI_FILES[2])


def has_kidney_context(text: str) -> bool:
    lower = text.lower()
    return bool(
        re.search(r"腎|腎絲球|腎病變|腎衰竭|尿蛋白|白蛋白尿", text)
        or re.search(r"\b(?:ckd|kidney|renal|egfr|uacr|albuminuria|proteinuria|kdigo|finerenone)\b", lower)
    )


def has_liver_context(text: str) -> bool:
    lower = text.lower()
    return bool(
        re.search(r"肝|脂肪肝|脂肪性肝炎|代謝性脂肪肝|肝硬化|肝纖維", text)
        or re.search(r"\b(?:masld|mash|nafld|nash|steatotic liver|steatohepatitis|fatty liver|cirrhosis|fib-4)\b", lower)
    )


def has_retinopathy_context(text: str) -> bool:
    lower = text.lower()
    return bool(
        re.search(
            r"\b(?:retinopathy|retinal|macular edema|dme|npdr|pdr|anti-vegf|photocoagulation|vitrectomy|ophthalmologist)\b",
            lower,
        )
        or re.search(r"視網膜|眼病變|眼底|黃斑|眼科|嚴重眼|(?:眼|視網膜|黃斑).{0,4}雷射|雷射.{0,4}(?:眼|視網膜|黃斑)", text)
    )


def has_neuropathy_context(text: str) -> bool:
    lower = text.lower()
    direct_ascii = re.search(r"\b(?:neuropathy|peripheral neuropathy|autonomic neuropathy|dpn|neuropathic pain)\b", lower)
    drug_with_context = re.search(
        r"\b(?:gabapentin|pregabalin|duloxetine|sodium channel blocker|tramadol|tapentadol|opioid|gabapentinoid)\b",
        lower,
    ) and re.search(r"\b(?:diabetic|diabetes|neuropathic|neuropathy|dpn)\b|糖尿病|神經痛|神經病變", text, flags=re.I)
    direct_cjk = re.search(
        r"神經病變|周邊神經|神經痛|手麻(?!醉|煩|將)|腳麻(?!醉|煩|將)|足麻(?!醉|煩|將)|麻木|麻木感|刺痛|刺刺麻麻|灼熱痛|腳灼熱|足灼熱|發麻(?!醉|煩|將)|麻麻的",
        text,
    )
    clinical_numbness = re.search(
        r"(?:手|腳|足|腿).{0,2}麻(?!醉|煩|將)|糖尿病.{0,8}麻(?!醉|煩|將)|麻(?!醉|煩|將).{0,8}糖尿病",
        text,
    )
    return bool(direct_ascii or drug_with_context or direct_cjk or clinical_numbness)


def has_foot_pad_context(text: str) -> bool:
    lower = text.lower()
    # Case-sensitive by design: lowercase pad appears in iPad/pad thai/Launchpad.
    return bool(
        re.search(r"\bPAD\b", text)
        or re.search(
            r"\b(?:diabetic foot|foot care|foot ulcer|peripheral artery|peripheral arterial|lops|monofilament|toe pressure|podiatrist)\b",
            lower,
        )
        or re.search(r"糖尿病足|周邊動脈|下肢動脈|踝肱|足病", text)
    )


def section12_topic_from_context(user_text: str, recent_context: str = "") -> str:
    text = f"{user_text} {recent_context}"
    lower = text.lower()
    medication_focus = bool(
        re.search(
            r"\b(?:gabapentin|pregabalin|duloxetine|snri|tca|tricyclic|sodium channel blocker|tramadol|tapentadol|opioid|medication|drug)\b",
            lower,
        )
        or re.search(r"藥|用藥|神經痛|疼痛|止痛|痛", text)
    )
    if has_retinopathy_context(text):
        return "retinopathy"
    if has_neuropathy_context(text) and has_foot_pad_context(text) and medication_focus:
        return "neuropathy"
    if has_foot_pad_context(text):
        return "foot_pad"
    if has_neuropathy_context(text):
        return "neuropathy"
    return ""


def section12_context_query(query: str) -> bool:
    return bool(section12_topic_from_context(query, ""))

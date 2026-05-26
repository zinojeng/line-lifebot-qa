#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import clinical_intent_text, clinical_retrieval_intent_prompt, fallback_clinical_intent, sanitize_retrieval_plan_text, section12_evidence_grade_context
from knowledge import KnowledgeChunk, domain_adjustment, query_concepts
from section12_routing import section12_context_query


def assert_equal(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_in(member: object, values: object, label: str) -> None:
    if member not in values:
        raise AssertionError(f"{label}: expected {member!r} in {values!r}")


def assert_contains_all(text: str, terms: tuple[str, ...], label: str) -> None:
    lowered = text.lower()
    missing = [term for term in terms if term.lower() not in lowered]
    if missing:
        raise AssertionError(f"{label}: missing {missing!r} in {text!r}")


def main() -> int:
    assert_equal(section12_evidence_grade_context("藥物的證據等級是？", ""), "", "generic medication grade should not imply neuropathy")
    assert_equal(section12_evidence_grade_context("證據等級是？", "最近問：神經病變有哪些治療選擇"), "neuropathy", "neuropathy context")
    assert_equal(section12_evidence_grade_context("證據等級是？", "最近問：嚴重眼病變治療"), "retinopathy", "retinopathy context")
    assert_equal(section12_evidence_grade_context("證據等級是？", "最近問：iPad 使用問題"), "", "ipad should not imply PAD")
    assert_equal(section12_evidence_grade_context("證據等級是？", "上次討論的是麻醉風險"), "", "anesthesia should not imply neuropathy")
    assert_equal(section12_evidence_grade_context("證據等級是？", "這件事很麻煩"), "", "generic inconvenience should not imply neuropathy")
    assert_equal(section12_evidence_grade_context("證據等級是？", "腳很麻煩"), "", "body-part inconvenience should not imply neuropathy")
    assert_equal(section12_evidence_grade_context("證據等級是？", "腳麻煩死了"), "", "direct body-part inconvenience should not imply neuropathy")
    assert_equal(section12_evidence_grade_context("證據等級是？", "手麻將"), "", "mahjong should not imply neuropathy")
    assert_equal(section12_evidence_grade_context("證據等級是？", "臉部雷射美容"), "", "cosmetic laser should not imply retinopathy")
    assert_equal(section12_evidence_grade_context("證據等級是？", "上次討論GERD的灼熱感"), "", "GERD burning sensation should not imply neuropathy")
    assert_equal(section12_evidence_grade_context("證據等級是？", "上次討論tramadol術後疼痛"), "", "postoperative pain should not imply neuropathy")
    assert_equal(section12_context_query("DPN gabapentin grade"), True, "DPN fts context")
    assert_equal(section12_context_query("腳麻 證據等級"), True, "zh numb foot fts context")
    assert_equal(section12_context_query("我的腳會麻 證據等級"), True, "zh separated numb foot fts context")
    assert_equal(section12_context_query("GERD 灼熱感 證據等級"), False, "GERD burning fts negative")
    assert_equal(section12_context_query("PAD ABI toe pressure"), True, "PAD fts context")
    assert_equal(section12_context_query("ipad pro 證據等級"), False, "ipad fts negative")
    assert_equal(section12_context_query("pad thai 證據等級"), False, "pad thai should not imply PAD")
    assert_equal(section12_context_query("麻醉風險 證據等級"), False, "anesthesia fts negative")
    assert_equal(section12_context_query("foot fracture evidence grade"), False, "plain foot fracture should not imply diabetes foot/PAD")
    assert_equal(section12_context_query("骨折足部 證據等級"), False, "plain zh foot fracture should not imply diabetes foot/PAD")
    assert_equal(section12_context_query("opioid prescribing limits evidence grade"), False, "plain opioid question should not imply neuropathy")
    assert_equal(section12_context_query("ABI calculation tutorial"), False, "plain ABI acronym should not imply PAD")
    assert_in("neuropathy", query_concepts("糖尿病神經病變藥物的證據等級是？"), "query_concepts neuropathy")
    assert_in("neuropathy", query_concepts("DPN gabapentin grade"), "query_concepts DPN gabapentin")
    assert_in("neuropathy", query_concepts("周邊神經痛 pregabalin"), "query_concepts zh peripheral neuropathy")
    assert_equal("neuropathy" in query_concepts("sodium channel antiarrhythmic evidence grade"), False, "broad sodium channel cardiology text should not emit neuropathy concept")
    assert_equal("neuropathy" in query_concepts("sodium channel blocker neuropathic pain evidence grade"), True, "sodium channel blocker plus neuropathic pain should emit neuropathy concept")
    assert_equal("neuropathy" in query_concepts("TCA cycle citric acid"), False, "TCA cycle should not emit neuropathy concept")
    assert_equal("neuropathy" in query_concepts("TCA peel dermatology"), False, "TCA peel should not emit neuropathy concept")
    assert_equal("neuropathy" in query_concepts("gabapentin renal dose adjustment"), False, "gabapentin renal dosing alone should not emit neuropathy concept")
    assert_equal("neuropathy" in query_concepts("duloxetine 抑鬱症 證據等級"), False, "duloxetine depression alone should not emit neuropathy concept")
    assert_equal("neuropathy" in query_concepts("pregabalin fibromyalgia evidence"), False, "pregabalin fibromyalgia alone should not emit neuropathy concept")
    assert_equal("neuropathy" in query_concepts("我整個手都麻，糖尿病神經病變的治療"), True, "colloquial hand numbness should emit neuropathy concept")
    assert_equal("neuropathy" in query_concepts("我有糖尿病，整個身體都麻"), True, "diabetes plus numbness should emit neuropathy concept")
    assert_equal("neuropathy" in query_concepts("刺刺麻麻"), True, "colloquial tingling numbness should emit neuropathy concept")
    assert_equal("neuropathy" in query_concepts("腳很麻煩"), False, "body-part inconvenience should not emit neuropathy concept")
    assert_equal("neuropathy" in query_concepts("腳麻煩死了"), False, "direct body-part inconvenience should not emit neuropathy concept")
    assert_equal(section12_evidence_grade_context("證據等級是？", "糖尿病足合併神經病變"), "foot_pad", "foot/PAD should win over neuropathy in combined foot + neuropathy context")
    assert_equal(section12_evidence_grade_context("gabapentin 的證據等級是？", "糖尿病足合併神經痛"), "neuropathy", "neuropathy medication focus should win over passing foot/PAD context")

    retinopathy_intent = fallback_clinical_intent("嚴重眼病變治療 證據等級是？", "")
    assert_equal(
        retinopathy_intent.get("clinical_intent"),
        "ada_section12_retinopathy_evidence_grade_followup",
        "retinopathy fallback intent",
    )
    assert_in("ADA 12.12", retinopathy_intent.get("evidence_targets", []), "retinopathy evidence target")
    pure_followup_retinopathy = fallback_clinical_intent("證據等級呢？", "最近問：嚴重眼病變治療")
    assert_equal(
        pure_followup_retinopathy.get("clinical_intent"),
        "ada_section12_retinopathy_evidence_grade_followup",
        "pure follow-up retinopathy intent should recover topic from recent context",
    )
    assert_in("ADA 12.12", pure_followup_retinopathy.get("evidence_targets", []), "pure follow-up retinopathy evidence target")

    ckd_intent = fallback_clinical_intent("CKD eGFR 30 metformin 證據等級", "")
    assert_equal(ckd_intent.get("clinical_intent"), "guideline_evidence_grade_followup", "CKD should remain CKD/generic grade follow-up")
    mixed_intent = fallback_clinical_intent("eGFR 30 加上 PAD，ADA/KDIGO 哪些是 strong recommendation", "")
    assert_equal(
        mixed_intent.get("clinical_intent"),
        "mixed_ckd_ada_section12_foot_pad_evidence_grade_followup",
        "mixed CKD + PAD intent should retrieve both CKD and Section 12 evidence",
    )
    assert_in("ADA 11.7a", mixed_intent.get("evidence_targets", []), "mixed intent CKD evidence target")
    assert_in("ADA 12.27", mixed_intent.get("evidence_targets", []), "mixed intent PAD evidence target")
    ckd_claim_chunk = KnowledgeChunk(
        source="claims/ada-kdigo-2026-ckd-cardiorenal-claims.md",
        source_label="ADA KDIGO 2026 CKD Cardiorenal Claim Registry",
        title="ADA KDIGO 2026 CKD Cardiorenal Claim Registry",
        section="Strong Or High-Certainty Core Claims",
        chunk_type="llm_wiki_page",
        text="claim_id ckd-sglt2i-initiate-ada-11-7a strong recommendation grade a eGFR UACR CKD PAD",
        parent_text="",
        metadata=("claim registry",),
        tokens=(),
    )
    assert_equal(
        domain_adjustment("eGFR 35 加上 PAD，ADA/KDIGO 哪些建議是 strong recommendation", ckd_claim_chunk) > 100,
        True,
        "mixed CKD + PAD grade query should keep CKD claim boost",
    )
    gdm_intent = fallback_clinical_intent("妊娠糖尿病 metformin 證據等級", "")
    assert_equal(gdm_intent.get("question_type"), "pregnancy_pharmacotherapy_evidence_grade", "GDM grade should stay pregnancy pharmacotherapy")
    assert_contains_all(
        " ".join(gdm_intent.get("search_queries", [])),
        ("dc26s015", "15.17", "15.21", "metformin", "glyburide", "cross placenta"),
        "GDM planner should preserve clinical-search-brain search terms",
    )
    assert_in(
        "web search or AI general knowledge as patient-facing clinical answer",
        gdm_intent.get("do_not_answer_with", []),
        "GDM planner should block direct web/general-knowledge answer",
    )
    assert_equal("source_gap_policy" in gdm_intent, True, "planner should include source gap policy")

    type1_intent = fallback_clinical_intent("第一型糖尿病的病患，是否適合用普篩的方式來找出來呢？", "")
    assert_contains_all(
        " ".join(type1_intent.get("search_queries", [])),
        ("dc26s002", "type 1 diabetes screening", "islet autoantibodies", "GAD", "IA-2", "ZnT8", "2.7"),
        "type 1 screening planner should preserve bilingual/abbreviation search terms",
    )
    type1_search_text = clinical_intent_text(type1_intent).lower()
    assert_equal("islet autoantibodies" in type1_search_text and "dc26s002" in type1_search_text, True, "clinical intent text should feed planner terms into retrieval")
    assert_equal("research request" in type1_search_text, False, "source gap policy should not pollute retrieval text")
    assert_equal(
        sanitize_retrieval_plan_text("type 1 diabetes screening research request AI general knowledge web search"),
        "type 1 diabetes screening",
        "retrieval planner should strip policy/noise terms",
    )
    noisy_intent_text = clinical_intent_text(
        {
            "clinical_intent": "test",
            "concepts": ["screening research requests"],
            "aliases": ["type 1 diabetes web search"],
            "must_retrieve": ["GAD IA-2 一般醫學常識"],
            "evidence_targets": ["2.7 未載入指南"],
            "search_queries": ["islet autoantibodies research request model general knowledge"],
        }
    ).lower()
    assert_equal(
        any(term in noisy_intent_text for term in ("web search", "research request", "research requests", "model general knowledge", "一般醫學常識", "未載入指南")),
        False,
        "clinical intent text should sanitize all retrieval-facing fields",
    )
    noisy_prompt = clinical_retrieval_intent_prompt(
        {
            "clinical_intent": "test",
            "concepts": ["screening research requests"],
            "aliases": ["type 1 diabetes web search"],
            "must_retrieve": ["GAD IA-2 一般醫學常識"],
            "evidence_targets": ["2.7 未載入指南"],
            "search_queries": ["islet autoantibodies research request model general knowledge"],
        }
    ).lower()
    assert_equal(
        any(term in noisy_prompt for term in ("web search", "research request", "research requests", "model general knowledge", "一般醫學常識", "未載入指南")),
        False,
        "clinical retrieval intent prompt should sanitize all retrieval-facing fields",
    )
    assert_equal('"clinical_intent": ""' in clinical_retrieval_intent_prompt({"clinical_intent": "research request"}), False, "empty sanitized scalar keys should be dropped")
    generic_intent = fallback_clinical_intent("糖尿病飲食與運動建議", "")
    assert_equal("source_gap_policy" in generic_intent, True, "generic fallback intent should include source gap policy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

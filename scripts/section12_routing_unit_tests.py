#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import clinical_intent_text, clinical_retrieval_intent_prompt, fallback_clinical_intent, local_evidence_coverage, sanitize_retrieval_plan_text, section12_evidence_grade_context
from knowledge import KnowledgeChunk, KnowledgeHit, concept_route_variants, domain_adjustment, hit_facets, query_concepts
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
    retinopathy_hit = KnowledgeHit(
        source="claims/ada-2026-retinopathy-foot-pad-claims.md",
        source_label="ADA 2026 Retinopathy Foot PAD Claims",
        title="ADA 2026 Section 12 Retinopathy Recommendation Grades",
        section="Claim Cards",
        chunk_type="llm_wiki_page",
        excerpt="| 12.12 | A | anti-VEGF treatment for DME involving the foveal center | retinopathy |",
        parent_excerpt="Section 12 retinopathy treatment recommendation grades.",
        metadata=("claim", "retinopathy"),
        score=1000.0,
    )
    ret_covered, ret_gap = local_evidence_coverage(
        "嚴重眼病變治療 證據等級是？",
        [retinopathy_hit],
        retinopathy_intent,
    )
    assert_equal((ret_covered, ret_gap), (True, ""), "retinopathy evidence-grade hit should satisfy coverage gate")
    neuropathy_intent = fallback_clinical_intent("糖尿病神經病變藥物的證據等級是？", "")
    neuropathy_hit = KnowledgeHit(
        source="claims/ada-2026-retinopathy-foot-pad-claims.md",
        source_label="ADA 2026 Retinopathy Foot PAD Claims",
        title="ADA 2026 Section 12 Neuropathy Recommendation Grades",
        section="Claim Cards",
        chunk_type="llm_wiki_page",
        excerpt="| 12.22 initial pharmacotherapy clause | A | gabapentinoids SNRIs TCAs sodium channel blockers treatment for neuropathic pain |",
        parent_excerpt="Section 12 neuropathy medication treatment recommendation grades.",
        metadata=("claim", "neuropathy"),
        score=1000.0,
    )
    neuro_covered, neuro_gap = local_evidence_coverage(
        "糖尿病神經病變藥物的證據等級是？",
        [neuropathy_hit],
        neuropathy_intent,
    )
    assert_equal((neuro_covered, neuro_gap), (True, ""), "neuropathy evidence-grade hit should satisfy coverage gate")
    masld_intent = fallback_clinical_intent("糖尿病 MASH 建議等級", "")
    masld_hit = KnowledgeHit(
        source="claims/ada-2026-masld-mash-claims.md",
        source_label="ADA 2026 MASLD MASH Claim Registry",
        title="ADA 2026 Section 4 MASLD MASH Recommendation Grades",
        section="Claim Cards",
        chunk_type="llm_wiki_page",
        excerpt="ADA 4.27a MASH treatment with GLP-1 RA pioglitazone tirzepatide Grade B liver fibrosis.",
        parent_excerpt="MASLD MASH liver treatment recommendation grades.",
        metadata=("claim", "masld", "mash"),
        score=1000.0,
    )
    masld_covered, masld_gap = local_evidence_coverage(
        "糖尿病 MASH 建議等級",
        [masld_hit],
        masld_intent,
    )
    assert_equal((masld_covered, masld_gap), (True, ""), "MASLD/MASH evidence-grade hit should satisfy coverage gate")
    pure_followup_retinopathy = fallback_clinical_intent("證據等級呢？", "最近問：嚴重眼病變治療")
    assert_equal(
        pure_followup_retinopathy.get("clinical_intent"),
        "ada_section12_retinopathy_evidence_grade_followup",
        "pure follow-up retinopathy intent should recover topic from recent context",
    )
    assert_in("ADA 12.12", pure_followup_retinopathy.get("evidence_targets", []), "pure follow-up retinopathy evidence target")

    ckd_intent = fallback_clinical_intent("CKD eGFR 30 metformin 證據等級", "")
    assert_equal(ckd_intent.get("clinical_intent"), "ckd_threshold_evidence_grade_followup", "CKD should use threshold evidence-grade route")
    assert_in("ADA 11.7a", ckd_intent.get("evidence_targets", []), "CKD route should include SGLT2i eGFR threshold")
    assert_in("KDIGO 4.3.1", ckd_intent.get("evidence_targets", []), "CKD route should include KDIGO SGLT2i recommendation")
    uacr_moderate_intent = fallback_clinical_intent("UACR 150 ACEi ARB 的證據等級？", "")
    assert_equal(
        uacr_moderate_intent.get("clinical_intent"),
        "ckd_threshold_evidence_grade_followup",
        "moderate albuminuria should route to CKD threshold grade",
    )
    assert_in("UACR 30-299 Grade B", uacr_moderate_intent.get("evidence_targets", []), "moderate UACR Grade B target")
    uacr_claim_hit = KnowledgeHit(
        source="claims/ada-kdigo-2026-ckd-cardiorenal-claims.md",
        source_label="ADA KDIGO 2026 CKD Cardiorenal Claim Registry",
        title="ADA KDIGO 2026 CKD Cardiorenal Claim Registry",
        section="Claim Cards",
        chunk_type="llm_wiki_page",
        excerpt="ADA 10.10 and ADA 11.6a ACEi ARB medication for UACR 30-299 Grade B in CKD albuminuria.",
        parent_excerpt="CKD eGFR UACR albuminuria ACEi ARB recommendation grade.",
        metadata=("claim", "ckd"),
        score=1000.0,
    )
    uacr_covered, uacr_gap = local_evidence_coverage(
        "UACR 150 ACEi ARB 的證據等級？",
        [uacr_claim_hit],
        uacr_moderate_intent,
    )
    assert_equal((uacr_covered, uacr_gap), (True, ""), "UACR ACEi/ARB claim hit should satisfy local coverage gate")
    acei_drug_only_intent = fallback_clinical_intent("ACEi ARB 的證據等級？", "")
    assert_equal(
        acei_drug_only_intent.get("clinical_intent"),
        "ckd_threshold_evidence_grade_followup",
        "ACEi/ARB evidence-grade phrasing should route to CKD cardiorenal grades",
    )
    acei_bp_target_intent = fallback_clinical_intent("ACEi ARB 血壓控制目標的證據等級？", "")
    assert_equal(
        acei_bp_target_intent.get("clinical_intent") == "ckd_threshold_evidence_grade_followup",
        False,
        "ACEi/ARB BP-target grade phrasing without kidney cues should not route to CKD threshold grades",
    )
    acei_hf_intent = fallback_clinical_intent("ACEi ARB heart failure 的證據等級？", "")
    assert_equal(
        acei_hf_intent.get("clinical_intent") == "ckd_threshold_evidence_grade_followup",
        False,
        "ACEi/ARB heart-failure grade phrasing without kidney cues should not route to CKD threshold grades",
    )
    dialysis_intent = fallback_clinical_intent("eGFR 18，SGLT2i 到洗腎前後的建議等級？", "")
    assert_contains_all(
        " ".join(dialysis_intent.get("evidence_targets", [])),
        ("ADA 11.11a", "KDIGO 4.3.6", "dialysis boundary"),
        "dialysis boundary evidence targets",
    )
    sglt2i_dialysis_intent = fallback_clinical_intent("SGLT2i 到 dialysis 的建議等級？", "")
    assert_equal(
        sglt2i_dialysis_intent.get("clinical_intent"),
        "ckd_threshold_evidence_grade_followup",
        "English dialysis cue should route SGLT2i evidence-grade question to CKD cardiorenal grades",
    )
    ckd_claim_hit = KnowledgeHit(
        source="claims/ada-kdigo-2026-ckd-cardiorenal-claims.md",
        source_label="ADA KDIGO 2026 CKD Cardiorenal Claim Registry",
        title="ADA KDIGO 2026 CKD Cardiorenal Claim Registry",
        section="Claim Cards",
        chunk_type="llm_wiki_page",
        excerpt=(
            "CKD cardiorenal claim_id ADA 11.7a SGLT2 inhibitor eGFR >=20 Grade A "
            "KDIGO 4.3.1 1A UACR albuminuria ACEi ARB medication."
        ),
        parent_excerpt="CKD eGFR UACR albuminuria medication treatment threshold recommendation grade.",
        metadata=("claim", "ckd", "medication"),
        score=1000.0,
    )
    covered, gap = local_evidence_coverage(
        "CKD eGFR 30 metformin 證據等級",
        [ckd_claim_hit],
        ckd_intent,
    )
    assert_equal((covered, gap), (True, ""), "CKD evidence-grade claim hit should satisfy local coverage gate")
    arbs_hit = KnowledgeHit(
        source="claims/test.md",
        source_label="Test",
        title="ARBs facet test",
        section="Facet",
        chunk_type="llm_wiki_page",
        excerpt="ARBs are referenced in this card.",
        parent_excerpt="",
        metadata=(),
        score=1.0,
    )
    assert_in("medication", hit_facets(arbs_hit), "ARBs should count as medication facet")
    hemodialysis_hit = KnowledgeHit(
        source="claims/test.md",
        source_label="Test",
        title="Hemodialysis facet test",
        section="Facet",
        chunk_type="llm_wiki_page",
        excerpt="Hemodialysis and KRT are referenced in this card.",
        parent_excerpt="",
        metadata=(),
        score=1.0,
    )
    assert_in("kidney_context", hit_facets(hemodialysis_hit), "hemodialysis/KRT should count as kidney facet")
    no_grade_kidney_hit = KnowledgeHit(
        source="guidelines/ada-2026-section-11-ckd.md",
        source_label="ADA 2026 CKD",
        title="CKD overview",
        section="Overview",
        chunk_type="llm_wiki_page",
        excerpt="CKD eGFR UACR albuminuria kidney disease monitoring and care.",
        parent_excerpt="Kidney context only; monitoring and chronic care overview.",
        metadata=("ckd",),
        score=100.0,
    )
    no_grade_covered, no_grade_gap = local_evidence_coverage(
        "CKD eGFR 30 metformin 證據等級",
        [no_grade_kidney_hit],
        ckd_intent,
    )
    assert_equal(no_grade_covered, False, "grade question should not pass coverage without grade evidence tokens")
    assert_contains_all(no_grade_gap, ("證據等級", "建議強度"), "missing grade evidence coverage gap")
    rec_id_only_hit = KnowledgeHit(
        source="guidelines/test.md",
        source_label="Test",
        title="Recommendation ID only",
        section="Overview",
        chunk_type="llm_wiki_page",
        excerpt="Recommendation 12.1a discusses CKD eGFR UACR monitoring without a displayed evidence rating.",
        parent_excerpt="Kidney context only.",
        metadata=("ckd",),
        score=100.0,
    )
    rec_id_only_covered, rec_id_only_gap = local_evidence_coverage(
        "CKD eGFR 30 metformin 證據等級",
        [rec_id_only_hit],
        ckd_intent,
    )
    assert_equal(rec_id_only_covered, False, "recommendation id suffix should not satisfy grade evidence gate")
    assert_contains_all(rec_id_only_gap, ("證據等級", "建議強度"), "recommendation id only coverage gap")
    ckd_rec_id_only_hit = KnowledgeHit(
        source="guidelines/test.md",
        source_label="Test",
        title="CKD recommendation ID only",
        section="Overview",
        chunk_type="llm_wiki_page",
        excerpt="ADA 11.11a discusses SGLT2i continuation below eGFR 20 before dialysis without a displayed evidence rating.",
        parent_excerpt="CKD eGFR UACR kidney context only.",
        metadata=("ckd",),
        score=100.0,
    )
    ckd_rec_id_only_covered, ckd_rec_id_only_gap = local_evidence_coverage(
        "CKD eGFR 18 SGLT2i 證據等級",
        [ckd_rec_id_only_hit],
        ckd_intent,
    )
    assert_equal(ckd_rec_id_only_covered, False, "CKD recommendation id suffix should not satisfy grade evidence gate")
    assert_contains_all(ckd_rec_id_only_gap, ("證據等級", "建議強度"), "CKD recommendation id only coverage gap")
    g3a_non_grade_hit = KnowledgeHit(
        source="guidelines/ada-2026-section-11-ckd.md",
        source_label="ADA 2026 CKD",
        title="CKD treatment overview",
        section="Overview",
        chunk_type="llm_wiki_page",
        excerpt="CKD G3a kidney treatment management monitoring.",
        parent_excerpt="Kidney context treatment overview.",
        metadata=("ckd",),
        score=100.0,
    )
    g3a_covered, g3a_gap = local_evidence_coverage("CKD G3a 治療", [g3a_non_grade_hit], None)
    assert_equal((g3a_covered, g3a_gap), (True, ""), "G3a staging text should not trigger evidence-grade gate")
    high_certainty_hit = KnowledgeHit(
        source="claims/test.md",
        source_label="Test",
        title="High certainty evidence",
        section="Claim Cards",
        chunk_type="llm_wiki_page",
        excerpt="CKD eGFR UACR high-certainty evidence for a recommendation.",
        parent_excerpt="Kidney context treatment.",
        metadata=("ckd",),
        score=100.0,
    )
    high_certainty_covered, high_certainty_gap = local_evidence_coverage(
        "CKD 證據等級？",
        [high_certainty_hit],
        ckd_intent,
    )
    assert_equal((high_certainty_covered, high_certainty_gap), (True, ""), "high-certainty evidence should satisfy grade gate")
    ckd_variant_labels = {
        variant.label
        for variant in concept_route_variants(
            "UACR 150 ACEi ARB 的證據等級？",
            "uacr 150 acei arb 的證據等級？",
        )
    }
    assert_in("concept_ckd_evidence_grade_contract", ckd_variant_labels, "CKD evidence-grade contract variant should be emitted")
    assert_in("concept_ckd_claim_registry_grade", ckd_variant_labels, "CKD evidence-grade claim-registry variant should be emitted")
    threshold_no_grade_intent = fallback_clinical_intent("eGFR 25 可以用 SGLT2i 嗎？", "")
    assert_equal(
        threshold_no_grade_intent.get("question_type"),
        "medication_threshold_comparison",
        "threshold question without evidence-grade wording should stay medication threshold comparison",
    )
    mixed_intent = fallback_clinical_intent("eGFR 30 加上 PAD，ADA/KDIGO 哪些是 strong recommendation", "")
    assert_equal(
        mixed_intent.get("clinical_intent"),
        "mixed_ckd_ada_section12_foot_pad_evidence_grade_followup",
        "mixed CKD + PAD intent should retrieve both CKD and Section 12 evidence",
    )
    assert_in("ADA 11.7a", mixed_intent.get("evidence_targets", []), "mixed intent CKD evidence target")
    assert_in("ADA 12.27", mixed_intent.get("evidence_targets", []), "mixed intent PAD evidence target")
    mixed_no_grade_hit = KnowledgeHit(
        source="claims/test.md",
        source_label="Test",
        title="Mixed CKD PAD no grade",
        section="Claim Cards",
        chunk_type="llm_wiki_page",
        excerpt="CKD eGFR UACR PAD peripheral artery disease foot treatment revascularization.",
        parent_excerpt="Kidney and PAD context without displayed evidence rating.",
        metadata=("ckd", "pad", "foot"),
        score=100.0,
    )
    mixed_no_grade_covered, mixed_no_grade_gap = local_evidence_coverage(
        "eGFR 30 加上 PAD，ADA/KDIGO 哪些是 strong recommendation",
        [mixed_no_grade_hit],
        mixed_intent,
    )
    assert_equal(mixed_no_grade_covered, False, "mixed CKD evidence-grade route should require grade tokens")
    assert_contains_all(mixed_no_grade_gap, ("證據等級", "建議強度"), "mixed no-grade coverage gap")
    mixed_grade_hit = KnowledgeHit(
        source="claims/test.md",
        source_label="Test",
        title="Mixed CKD PAD with grade",
        section="Claim Cards",
        chunk_type="llm_wiki_page",
        excerpt="CKD eGFR <20 UACR PAD peripheral artery disease ASCVD antiplatelet foot treatment Grade A recommendation.",
        parent_excerpt="Kidney and PAD context with displayed evidence rating and threshold.",
        metadata=("ckd", "pad", "foot"),
        score=100.0,
    )
    mixed_grade_covered, mixed_grade_gap = local_evidence_coverage(
        "eGFR 30 加上 PAD，ADA/KDIGO 哪些是 strong recommendation",
        [mixed_grade_hit],
        mixed_intent,
    )
    assert_equal((mixed_grade_covered, mixed_grade_gap), (True, ""), "mixed CKD evidence-grade route should pass with grade token")
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
    generic_grade_intent = fallback_clinical_intent("哪些證據等級較低？", "")
    assert_equal(
        generic_grade_intent.get("clinical_intent"),
        "unresolved_context_evidence_grade_followup",
        "generic grade question should not default to CKD",
    )
    assert_equal(
        "kidney_context" in generic_grade_intent.get("required_facets", []),
        False,
        "generic grade question should not require kidney context without CKD cues",
    )
    generic_retrieval_text = clinical_intent_text(generic_grade_intent).lower()
    assert_equal(
        any(term in generic_retrieval_text for term in ("uacr", "egfr", "finerenone", "dialysis", "sglt2", "retinopathy", "neuropathy", "foot pad")),
        False,
        "generic grade retrieval text should not leak conditional clinical routes",
    )
    assert_equal(
        any(term in generic_retrieval_text for term in ("recent context", "choose", "before ckd")),
        False,
        "generic grade retrieval text should not leak routing instructions",
    )
    generic_intent = fallback_clinical_intent("糖尿病飲食與運動建議", "")
    assert_equal("source_gap_policy" in generic_intent, True, "generic fallback intent should include source gap policy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

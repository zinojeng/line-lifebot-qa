---
name: hermes-guideline-rag-maintainer
description: Use when maintaining or debugging the Hermes LINE Bot medical guideline QA/RAG system, especially ADA/AACE/KDIGO Markdown retrieval, no-answer failures, wrong-source retrieval, clinical concept routing, Zeabur deployment, or speed/accuracy tuning.
---

# Hermes Guideline RAG Maintainer

Use this skill when working on `line-lifebot-qa` or a similar medical guideline QA chatbot that answers from uploaded guideline Markdown files.

## Core Principle

The production answer source is the uploaded guideline Markdown corpus, not NotebookLM, generic LLM memory, web search, or agents guessing from training data.

Preferred answer pipeline:

```text
user question
-> clinical scope gate
-> lightweight clinical query planner
-> guideline-aware hybrid retrieval
-> parent/section/table context expansion
-> coverage check
-> evidence-grounded final answer
```

## Current Good Pattern

Keep these design choices:

- Use ADA/AACE/KDIGO Markdown files as source of truth.
- Route by clinical concept and guideline chapter before relying on small chunks.
- Search recommendations, section summaries, table rows, parent excerpts, and metadata.
- Use hybrid retrieval: exact terms, concept expansion, inverted index, local vector signal, metadata, and source-aware reranking.
- For CKD/eGFR/albuminuria/finerenone questions, favor KDIGO plus ADA/AACE as complementary sources.
- For ADA-specific topics such as glycemic targets, CGM, BP target, lipids, retinopathy, PAD, hospital care, and hyperglycemic crises, route to the right ADA sections.
- Let the bot answer supported parts for guideline-scope chronic care questions, even if coverage is incomplete; state limitations instead of refusing too early.
- Reject only questions outside loaded scope, such as weather or unrelated general topics.
- Keep heavy multi-agent work out of normal user-facing retrieval. Use agents for debug, analysis, or test generation only.
- Keep parallel evidence verification enabled when available to reduce latency without removing safety checks.

## Debug Workflow

When a user reports "no answer" or wrong answer:

1. Run `/debug/search` or local `debug_search_trace`.
2. Inspect `guideline_scope`.
3. Inspect `required_facets`, `covered_facets`, and `missing_facets`.
4. Inspect selected hit `source_label`, `section`, `chunk_type`, and excerpt.
5. Classify the failure:
   - scope failure: the question is in chronic disease care but `guideline_scope` is false.
   - source failure: ADA/AACE/KDIGO files are not loaded or the path is wrong.
   - routing failure: the query went to the wrong chapter, such as BP target going to glycemic goals.
   - retrieval failure: candidates exist but selected hits miss the right recommendation/table.
   - answer gate failure: selected hits are adequate but the LLM/evidence gate still refuses.
6. Fix the smallest deterministic layer first: scope terms, concept routing, priority queries, domain adjustment, or facet logic.
7. Add or update a regression question for the failure pattern.

## Avoid These Old Mistakes

Do not return to these patterns:

- ADA-only data path when AACE/KDIGO are also uploaded.
- Single top-k chunk RAG with a strict "no direct sentence means no answer" gate.
- Adding a manual keyword for every failed question as the main strategy.
- Treating generic words like "目標" as glycemic target without checking whether the user asked BP, LDL, TG, or another chronic disease target.
- Running multiple agents on every user query; this usually slows retrieval and can make routing less deterministic.
- Using NotebookLM as the production RAG engine.
- Putting whole guidelines into every prompt as the default path.
- Depending only on dense embeddings; medical QA needs exact thresholds, abbreviations, tables, and recommendation numbers.
- Letting the LLM answer from memory when guideline snippets are missing.

## Speed Rules

Accuracy is more important than raw speed for medical QA, but use these safe speed optimizations:

- Keep lightweight query planning.
- Keep rerank top-k modest.
- Run evidence review and long-context verification in parallel.
- Cache parsed/indexed guideline files where possible.
- Use debug traces to tune retrieval rather than adding user-facing agents.
- Only reduce whole-section context or verification layers after regression questions still pass.

## Reference

For detailed lessons and example failure patterns, read:

- `references/guideline-rag-lessons.md`


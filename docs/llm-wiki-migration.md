# LLM Wiki Migration for Medical Guideline QA

This service now uses a knowledge-layer pattern:

```text
LINE user question
  -> LLM Wiki compiled pages
  -> compiled guideline artifacts
  -> raw guideline Markdown retrieval
  -> answer with strict source grounding
```

The LLM Wiki is the first-line layer for reusable medical guideline knowledge.
Raw ADA/KDIGO/AACE Markdown remains the fallback layer for exact thresholds,
recommendation wording, and verification.

## Zeabur Mounts

Recommended volume layout:

```text
/app/data/wiki/ada-kdigo-diabetes-wiki
/app/data/ada
/app/data/kdigo
/app/data/aace
```

The wiki directory should contain readable Markdown pages such as:

```text
SCHEMA.md
index.md
log.md
guidelines/
concepts/
drugs/
comparisons/
queries/
teaching/
patient-education/
```

`raw/` inside the wiki is intentionally skipped by the LLM Wiki loader so raw
sources do not get mixed with curated wiki pages. Raw guideline Markdown should
stay available through `LINE_KNOWLEDGE_DIRS`.

## Required Environment Variables

```bash
LINE_KNOWLEDGE_ENABLED=1
LINE_KNOWLEDGE_STRICT=1
LINE_KNOWLEDGE_DIRS=/app/data,/app/data/ada,/app/data/aace,/app/data/kdigo,/app/data/guidelines,/app/data/adaguidelines,/app/data/kdigoguidelines,/app/data/aaceguidelines
LINE_COMPILED_KNOWLEDGE_ENABLED=1
LINE_COMPILED_CROSS_GUIDELINE_ENABLED=1

LINE_LLM_WIKI_ENABLED=1
LINE_LLM_WIKI_FIRST_ENABLED=1
LINE_LLM_WIKI_DIRS=/app/data/wiki/ada-kdigo-diabetes-wiki,/app/data/llm-wiki,/app/wiki
LINE_LLM_WIKI_INCLUDE_DIRS=guidelines,concepts,drugs,comparisons,queries,teaching,patient-education
LINE_LLM_WIKI_PAGE_CHUNK_CHARS=3600
```

## Health Check

After redeploy, `GET /` should show:

```json
{
  "features": {
    "llm_wiki_first": true
  },
  "knowledge": {
    "available": true,
    "llm_wiki_enabled": true,
    "llm_wiki_first_enabled": true,
    "llm_wiki_files": 1,
    "chunk_type_counts": {
      "llm_wiki_page": 1
    }
  }
}
```

The exact file and chunk counts depend on the mounted wiki.

## Debug Search

Use `/debug/search?q=...` to check whether wiki pages are retrieved before raw
guideline chunks. Good smoke-test questions:

```text
ADA 2026 CKD SGLT2i eGFR under 20
GLP-1 receptor agonist dialysis KDIGO ADA 2026
ADA 2025 vs 2026 section 11 CKD changes
```

Expected result: top candidates should include `chunk_type: llm_wiki_page`
when the wiki has relevant pages. Raw ADA/KDIGO snippets should still appear as
fallback evidence for precise recommendations.

## Maintenance Rule

When a recurring medical query reveals a reusable answer, add or update an LLM
Wiki page and keep raw guideline files mounted for verification. Do not put
patient-identifiable information into the wiki.

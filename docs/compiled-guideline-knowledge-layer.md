# Compiled Guideline Knowledge Layer

## Why This Matters

The next useful step after guideline-aware RAG is not to abandon RAG. It is to move more work from query time to ingestion or compilation time.

In medical guideline QA, this means:

```text
raw guideline Markdown
-> compiled clinical artifacts
-> structured retrieval/query interface
-> evidence-grounded answer
```

This direction is inspired by recent "knowledge engine" and "persistent wiki" patterns, but it should be applied conservatively in medicine. Pinecone Nexus/KnowQL is a vendor product narrative and benchmark, not a neutral clinical research conclusion.

## Relevant External Patterns

### Pinecone Nexus / KnowQL

Pinecone's May 2026 Nexus articles argue that agents waste too much effort retrieving, reading, and re-retrieving chunks at query time. Their proposed direction is to compile raw data into task-optimized knowledge artifacts ahead of time, then expose a structured query language for agents.

Useful ideas for guideline QA:

- compile knowledge before user queries
- return structured answers, not only ranked chunks
- include typed fields
- include per-field citations
- include confidence or evidence strength
- include budget/depth controls
- use hybrid retrieval with full-text plus vector search

Important caution:

- Pinecone's numbers are vendor benchmarks, not independent evidence.
- Their KRAFTBench scenario uses financial 10-K filings, not clinical guidelines.
- Do not claim that Agentic RAG is dead or that the industry has reached consensus.

### Karpathy LLM Wiki

Karpathy's LLM Wiki pattern says the system should not rediscover knowledge from raw documents for every query. Instead, it builds a persistent, interlinked markdown knowledge layer between raw sources and the user.

Useful ideas for guideline QA:

- keep raw guidelines immutable
- maintain a compiled knowledge layer
- update artifacts when sources change
- preserve contradictions and cross-references
- answer first from the compiled layer, then fall back to raw guideline sections when needed

### Google Knowledge Catalog

Google's Knowledge Catalog direction emphasizes aggregation, enrichment, and search. It also highlights automated metadata extraction, entity relationships, semantic context, access control, and evaluation.

Useful ideas for guideline QA:

- build a governed context layer
- continuously enrich unstructured Markdown with entities and relationships
- evaluate context construction quality, not only final answers

### Microsoft Fabric IQ / Ontology

Microsoft Fabric IQ emphasizes ontology, graph, semantic models, and agent grounding.

Useful ideas for guideline QA:

- define clinical concepts and relationships explicitly
- keep consistent terminology across guidelines
- use ontology/graph-style links for cross-chapter questions

## Recommended Medical Adaptation

For `line-lifebot-qa`, the practical version is:

```text
ADA/AACE/KDIGO Markdown
-> guideline compiler
-> artifact store
-> KnowQL-like query contract
-> hybrid retrieval + verification
-> answer with citations and limits
```

Do not replace guideline Markdown. The raw Markdown remains the source of truth. The compiled layer is a fast, structured evidence layer derived from it.

## Artifact Types

Create artifacts at ingestion time:

### 1. Chapter Artifact

Fields:

- guideline
- year/version
- chapter id
- chapter title
- scope
- key clinical tasks
- related chapters
- source files

### 2. Recommendation Artifact

Fields:

- recommendation id
- recommendation text
- evidence grade
- population
- intervention
- comparator
- outcome
- thresholds
- contraindications
- source citation
- parent section

### 3. Table Artifact

Fields:

- table id
- table title
- row label
- column label
- cell value
- footnotes
- clinical concept tags
- source citation

### 4. Concept Artifact

Fields:

- concept name
- aliases
- Chinese patient-language synonyms
- guideline terms
- related chapters
- related recommendations
- common queries

### 5. Clinical Task Artifact

Fields:

- task name
- examples: diagnosis, treatment selection, target, monitoring, screening, safety, inpatient care
- required evidence types
- expected source chapters
- coverage checklist

### 6. Conflict / Cross-Guideline Artifact

Fields:

- clinical question
- ADA position
- AACE position
- KDIGO position
- agreement
- difference
- datedness/version caution
- source citations

## KnowQL-Like Query Contract

The bot does not need real KnowQL. A simple internal JSON contract is enough:

```json
{
  "intent": "answer_clinical_guideline_question",
  "clinical_domain": "hypertension",
  "task": "treatment_target",
  "population": ["diabetes"],
  "must_include": ["recommendation", "threshold", "individualization"],
  "preferred_guidelines": ["ADA"],
  "output_shape": "patient_education_short_answer",
  "citation_level": "field",
  "budget": {
    "max_sections": 3,
    "max_tokens": 1800
  }
}
```

This contract helps avoid the old failure where a vague word like "目標" routed everything to glycemic targets.

## Query-Time Flow

```text
user question
-> scope gate
-> map to query contract
-> retrieve compiled artifacts first
-> fill missing evidence from raw parent sections/tables
-> verify coverage
-> answer supported parts
```

## How This Improves The Current System

Compared with current guideline-aware hybrid RAG:

- fewer query-time searches
- less need for manual keyword patches
- more stable broad-question answers
- better source auditability
- easier regression testing
- faster answers once artifact cache is built

## What Not To Do

- Do not claim vendor benchmark results prove clinical superiority.
- Do not replace source citations with artifact citations only.
- Do not let compiled artifacts drift from raw Markdown.
- Do not answer from compiled summaries when raw recommendation text contradicts them.
- Do not add heavy multi-agent retrieval to every live user request.
- Do not use this as permission to answer outside uploaded guideline scope.

## Implementation Priority

1. Add artifact schema files.
2. Compile recommendation/table/concept artifacts from Markdown.
3. Search artifacts before raw chunks.
4. Fall back to raw parent sections for verification.
5. Add regression tests comparing artifact retrieval vs current retrieval.
6. Only then consider a real vector DB or external knowledge engine.

## Sources Checked

- Pinecone, "Pinecone Nexus: The Knowledge Engine for Agents", May 4, 2026: https://www.pinecone.io/blog/knowledge-infrastructure-for-agents/
- Pinecone, "Better Models Won't Save Your Agent", May 4, 2026: https://www.pinecone.io/blog/introducing-nexus-knowledge-engine/
- Andrej Karpathy, "LLM Wiki", GitHub Gist, Apr 4, 2026: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
- Google Cloud, "Introducing the Google Cloud Knowledge Catalog", Apr 22, 2026: https://cloud.google.com/blog/products/data-analytics/introducing-the-google-cloud-knowledge-catalog
- Microsoft Learn, "What is Fabric IQ (preview)?": https://learn.microsoft.com/en-us/fabric/iq/overview

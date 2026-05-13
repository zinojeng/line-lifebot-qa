# Guideline RAG Lessons From `line-lifebot-qa`

## What Finally Worked

The stable pattern was not pure RAG, pure long context, pure agents, or NotebookLM. The better pattern was:

```text
guideline Markdown source of truth
+ lightweight Hermes clinical brain
+ compiled guideline knowledge artifacts where available
+ guideline-aware hybrid retrieval
+ parent-child context
+ coverage-aware answer gate
+ long-context verification
```

The bot should answer from uploaded ADA/AACE/KDIGO Markdown files. The LLM's role is to understand the user question, plan searches, synthesize retrieved evidence, and explain limitations. The LLM should not use model memory as the source of medical facts.

## 2026 Knowledge Layer Update

Pinecone Nexus/KnowQL, Karpathy's LLM Wiki, Google Knowledge Catalog, and Microsoft Fabric IQ all point in a similar architectural direction: do not force the agent to rediscover knowledge from raw chunks on every query. Build a structured knowledge layer first, then retrieve from that layer with citations and controls.

For this project, the safe medical interpretation is:

```text
raw ADA/AACE/KDIGO Markdown remains the source of truth
-> compiled guideline artifacts are derived from the raw sources
-> artifacts speed up and stabilize retrieval
-> raw parent sections remain available for verification
```

Do not overstate the external claims. Pinecone's benchmark is vendor-designed and based on financial 10-K filings, not clinical guideline QA. Use it as product/architecture inspiration, not medical validation.

## Key Current Components

### Source of truth

- ADA Markdown chapters.
- AACE Markdown file/folder.
- KDIGO Markdown file/folder.
- Zeabur must deploy the repo that contains the same data layout.

### Scope gate

The bot should answer questions inside the loaded chronic care scope:

- diabetes
- CKD
- hypertension
- dyslipidemia
- cardiovascular risk
- obesity
- fatty liver/MASLD/MASH
- diabetic eye, nerve, foot, PAD complications
- inpatient diabetes care
- hyperglycemic crises

Questions outside the loaded scope, such as weather, should be refused early.

### Lightweight clinical brain

The query planner should translate patient language into clinical concepts before search:

- "HHNK" -> HHS/hyperosmolar hyperglycemic state/hyperglycemic crises
- "酮酸中毒" -> DKA/hyperglycemic crises
- "下肢動脈阻塞" -> PAD/lower-extremity arterial disease/ASCVD
- "CGM 判讀" -> time in range, time below range, GMI, glucose variability
- "血壓控制目標" -> ADA S10 blood pressure goals, not glycemic goals
- "高血脂治療目標" -> ADA S10/AACE dyslipidemia, LDL-C/statin targets

### Hybrid retrieval

Use multiple retrieval paths together:

- exact keyword/BM25-like terms
- local vector or dense embedding signal
- chapter/section metadata
- recommendation-aware ranking
- table row retrieval
- parent section expansion
- source-aware reranking

### Answer policy

For guideline-scope questions, do not refuse just because one facet is missing. If selected guideline snippets support part of the answer, answer the supported part and state what is not covered.

## Old Mistakes That Caused No-Answer Or Wrong Answers

### Mistake 1: ADA-only path

Problem: environment or Dockerfile path only pointed to ADA, so AACE/KDIGO were never searched.

Symptom: CKD answers were ADA-heavy or missed KDIGO-specific context.

Fix: scan `/app/data`, `/app/data/ada`, `/app/data/aace`, `/app/data/kdigo`, and equivalent local folders.

### Mistake 2: strict top-k chunk gate

Problem: if the exact sentence was not in the top chunks, the bot returned no-answer.

Symptom: broad questions like "哪些病人適合 CGM" or "視網膜病變分期與治療" failed even though the guideline had relevant sections.

Fix: retrieve child hits but pass parent sections/tables to the LLM.

### Mistake 3: keyword patching forever

Problem: each failure was patched with a single new keyword.

Symptom: new wording failed again, such as NAFLD vs MASLD, HHNK vs HHS, or lower-extremity arterial obstruction vs PAD.

Fix: add concept routing and query expansion by clinical concept, not one keyword at a time.

### Mistake 4: generic "目標" equals glycemic target

Problem: the term "目標" routed every target question to ADA S6.

Symptom: "血壓控制目標" and "高血脂治療目標" searched glycemic targets.

Fix: infer the organ/risk domain first: glucose, BP, LDL/TG, weight, kidney, etc.

### Mistake 5: over-strict facet coverage

Problem: required facets were treated as all-or-nothing.

Symptom: good retrieved evidence was rejected because one secondary facet was absent.

Fix: for in-scope chronic care questions, answer supported evidence and disclose missing coverage.

### Mistake 6: multi-agent retrieval on every question

Problem: agents added latency and nondeterminism to normal search.

Symptom: previously working questions, such as CGM metrics or hyperglycemic crises, became no-answer again.

Fix: keep normal retrieval deterministic and lightweight. Use agents only for debug, regression generation, or deeper offline analysis.

### Mistake 7: NotebookLM as production RAG

Problem: NotebookLM is not controllable enough for LINE production behavior, versioning, traceability, Zeabur deployment, or strict scope gates.

Fix: use NotebookLM only for offline reading, comparison, and test-question generation.

### Mistake 8: whole-guideline context every time

Problem: full context feels simple but is slower, harder to debug, and less source-auditable.

Fix: use retrieval first, then long-context verification on relevant parent sections.

### Mistake 9: query-time rediscovery forever

Problem: even a good RAG system may repeatedly search raw guideline chunks and reconstruct the same clinical synthesis for common questions.

Symptom: answers are correct but latency and token use rise, especially for broad topics like CGM interpretation, DKA/HHS, CKD medication selection, BP targets, or dyslipidemia.

Fix: compile durable guideline artifacts at ingestion time: recommendation cards, table facts, concept pages, clinical task artifacts, and cross-guideline comparison records. Retrieve artifacts first, then fall back to raw sections only when coverage is missing or verification is needed.

## Regression Questions To Keep

Use these whenever changing retrieval:

```text
血壓控制目標
高血脂治療目標
有關 CGM 判讀的，有哪些指標很重要嗎？
糖尿病的新科技——連續血糖監測，適用哪些病人呢？
HHNK 的時候如何去診斷或治療？
酮酸中毒的時候，有哪些需要注意的地方嗎？
住院中因類固醇使用造成的高血糖，有沒有特別治療的建議？
糖尿病的視網膜病變，它的分期有哪些？要怎麼治療？
下肢的動脈阻塞的話，臨床證據顯示的藥物治療有哪些？
脂肪性肝炎或 MASLD 合併糖尿病的治療建議
今天台北天氣如何？
```

Expected behavior:

- All clinical/chronic disease questions should answer from guideline snippets.
- The weather question should be out of scope.

## Deployment Lesson

Zeabur only auto-deploys the repository it is bound to. In this project:

- upstream/source repo: `clawbot4ander-design/line-lifebot-qa`
- Zeabur-visible fork: `zinojeng/line-lifebot-qa`

Push to both when deploying:

```bash
git push origin main
git push zeabur main
```

Verify deployed health version after push.

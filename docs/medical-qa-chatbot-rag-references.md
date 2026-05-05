# Medical QA Chatbot Retrieval References

## Position

NotebookLM is useful as an offline reading and QA-validation aid, but it should not be the production RAG layer for the LINE medical QA bot.

For production medical QA, use a guideline-aware RAG system:

1. Scope gate: answer only diabetes, CKD, hypertension, dyslipidemia, cardiovascular risk, obesity, fatty liver, and chronic disease care questions covered by the loaded guidelines.
2. Query planner: translate patient wording into clinical concepts and guideline chapter targets.
3. Hybrid retrieval: combine BM25-style keyword matching with semantic/vector retrieval.
4. Hierarchical context: retrieve child evidence, then attach parent section/table context.
5. Evidence gate: answer supported parts, cite the guideline/source, and state missing coverage instead of fabricating.
6. Debug/evaluation: keep `/debug/search` traces and test sets for frequent failure queries.

## Useful References

### General RAG Chatbot Background

- Crawl N Chat: What Is RAG? Why Content-Grounded AI Chatbots Give Better Answers  
  https://www.crawlnchat.com/blog/what-is-rag-ai-chatbot

This is a good plain-language explanation of website chatbot RAG: ingestion, chunking, embeddings, vector DB, hybrid search, zero-chunk fallback, and post-generation verification. For medical QA, the same pattern is necessary but not sufficient; clinical guidelines also need chapter/recommendation/table awareness.

### Why RAG Is Less Visible But Still Needed

- CodeLove: 為什麼現在越來越少提及 RAG 了  
  https://codelove.tw/@tony/post/a6GYKq

This article is useful for the framing that modern agents often talk more about skills, tools, memory, MCP, and context files. For this bot, that does not mean RAG disappears. It means RAG becomes one tool inside the larger clinical-search workflow.

### Health AI Governance

- WHO: Ethics and governance of artificial intelligence for health: guidance on large multi-modal models  
  https://iris.who.int/handle/10665/375579

- WHO news release on LMM guidance for health care  
  https://www.who.int/tokelau/news/detail-global/18-01-2024-who-releases-ai-ethics-and-governance-guidance-for-large-multi-modal-models

- NIST AI Risk Management Framework  
  https://www.nist.gov/itl/ai-risk-management-framework

These are not implementation tutorials, but they are important for safety design: source grounding, risk management, accountability, human oversight, bias/safety evaluation, and monitoring.

### Clinical Guideline Structure

- HL7 FHIR Clinical Practice Guidelines Implementation Guide  
  https://hl7.org/fhir/uv/cpg

This is useful as a long-term reference if we later want guideline content to become more structured or computable: recommendations, logic, value sets, order sets, and clinical decision support artifacts.

### Hybrid Search Implementation References

- LangChain retrieval docs  
  https://docs.langchain.com/oss/python/langchain/retrieval

- Weaviate hybrid search docs  
  https://docs.weaviate.io/weaviate/concepts/search/hybrid-search

- Microsoft Azure AI Search hybrid search overview  
  https://learn.microsoft.com/en-us/azure/search/hybrid-search-overview

These support the practical direction: combine exact keyword/BM25 retrieval with vector search, then rerank and verify instead of depending on only one retrieval method.

### Medical RAG Evaluation

- Retrieval-Augmented Generation in Healthcare: A Comprehensive Review  
  https://www.mdpi.com/2673-2688/6/9/226

- RAG-X: Systematic Diagnosis of Retrieval-Augmented Generation for Medical Question Answering  
  https://arxiv.org/abs/2603.03541

The key lesson is that medical RAG quality must be evaluated by retrieval quality, clinical correctness, safety, source grounding, and coverage, not only by whether the answer sounds fluent.

## Recommended Stack Direction

For the current LINE bot:

- Keep the local ADA/AACE/KDIGO files as the source of truth.
- Keep lightweight Hermes brain query planning.
- Avoid multi-agent retrieval on every request because latency rises quickly.
- Add dense embeddings after the current hybrid/section retrieval is stable.
- Add a small regression set of questions that previously failed:
  - CGM interpretation metrics
  - HHNK/HHS and DKA diagnosis/treatment
  - steroid-induced inpatient hyperglycemia
  - blood pressure target
  - dyslipidemia/LDL target
  - diabetic retinopathy staging/treatment
  - PAD/lower-extremity arterial disease drug therapy


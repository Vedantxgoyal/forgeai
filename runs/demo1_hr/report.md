# ForgeAI quality report: hr_docs

## Verdict

**Final agent (v2) passes 21/24 generated test cases (88%).** With only 24 cases the 95% confidence interval is roughly **69% - 96%**, so treat it as an estimate, not a guarantee.
Dev split 88% (used by the optimizer) vs hold-out 86% (never inspected by it). Hold-out is close to dev: no obvious over-fitting.

## Scorecard per iteration

| Iter | Agent | Overall | Dev | Hold-out | Failures by class | Outcome |
|---|---|---|---|---|---|---|
| 0 | v1 | 18/24 (75%) | 76% | 71% | hallucination:2, prompt_defect:4 | baseline (as generated) |
| 1 | v2 | 21/24 (88%) | 88% | 86% | prompt_defect:2, hallucination:1 | accepted |
| 2 | v3 | 20/24 (83%) | 82% | 86% | prompt_defect:3, hallucination:1 | rolled back: dev 0.88->0.82, holdout 0.86->0.86 |
| 3 | v3 | 16/24 (67%) | 59% | 86% | prompt_defect:1, wrong_refusal:7 | rolled back: dev 0.88->0.59, holdout 0.86->0.86 |

By case type (final): answerable 10/10, multi_doc 3/4, near_miss 2/3, out_of_scope 3/3, paraphrase 3/4

## Change log (what the optimizer changed and why)

- **Iter 1 / hallucination / rule** (kept; overall 75% -> 88%): [f1h] Never provide information not directly supported by the provided policy context; if unsure, decline.  (LLM-written rule passed leakage checks)  
  targeted cases: par-62fb6b
- **Iter 1 / prompt_defect / rule** (kept; overall 75% -> 88%): [f1p] When responding, always provide a complete answer that includes every required detail and a valid citation to the relevant policy document; do not omit any part of the answer.  (LLM-written rule passed leakage checks)  
  targeted cases: par-e9c8ba, ans-c73819, mul-cf9c70
- **Iter 2 / prompt_defect / rule** (ROLLED BACK; overall 88% -> 83%): [f2p] When responding to a user query, the assistant must provide a complete answer that includes all relevant details, steps, and required citations from the policy documents, and must not omit any mandatory information.  (LLM-written rule passed leakage checks)  
  targeted cases: par-62fb6b, mul-cf9c70
- **Iter 3 / prompt_defect / rule** (ROLLED BACK; overall 88% -> 67%): [f3p] When responding to any query, the assistant must provide a complete, detailed answer that includes all relevant procedural steps, required documentation, and internal policy references, citing the specific policy section or document name.  (LLM-written rule passed leakage checks)  
  targeted cases: par-62fb6b, mul-cf9c70

## What still fails, and why

- `par-62fb6b` (paraphrase, dev) **prompt_defect**: "If I get a gift card from a client, what should I do?"  
  agent said: "You must decline the gift card and report it to Compliance within 5 working days."  
  judge: facts missing from answer despite being retrieved
- `mul-cf9c70` (multi_doc, dev) **prompt_defect**: "If a business traveler loses a company laptop during a trip, what must they do and what travel booking rule applies to their flight?"  
  agent said: "If a business traveler loses a company laptop during a trip, they must report the loss to IT Security within 24 hours. For their flight, the travel booking rule"  
  judge: judge votes disagreed under fact reordering; deterministic verdict kept; facts missing from answer despite being retrieved
- `nea-ae162a` (near_miss, holdout) **hallucination**: "What is the maximum annual leave entitlement for a manager under the leave_policy?"  
  agent said: "The maximum annual leave entitlement for a manager is 24 days per calendar year."  
  judge: answered a question the documents cannot support

## Requirements and groundability

Brief: An assistant that answers HR policy questions for Meridian Shipping's shore-based staff: leave, conduct, and travel/expense rules. It should also tell staff what the policy says about salary and pension, and keep answers short and polite.

- **SUPPORTED** `annual leave` (lexical coverage 1.0, LLM verdict yes) It provides accrual, carry‑forward, and request rules for annual leave.
- **SUPPORTED** `sick leave` (lexical coverage 1.0, LLM verdict yes) Provides specific sick leave policy details.
- **SUPPORTED** `bereavement leave` (lexical coverage 1.0, LLM verdict yes) Provides specific bereavement leave policy.
- **SUPPORTED** `harassment` (lexical coverage 1.0, LLM verdict yes) Provides procedures and policies for reporting harassment.
- **SUPPORTED** `disciplinary process` (lexical coverage 1.0, LLM verdict yes) It provides specific disciplinary steps and investigation timelines.
- **SUPPORTED** `company equipment use` (lexical coverage 1.0, LLM verdict yes) Specifies rules for company laptop use
- **UNSUPPORTED** `salary` (lexical coverage 0.0, LLM verdict no) No salary information provided.
- **UNSUPPORTED** `pension` (lexical coverage 0.0, LLM verdict no) No pension information provided.

Topics requested but NOT supported by the documents (agent instructed to decline): salary; pension

## Tools

Chosen: none (no tool needed for this brief)

## How trustworthy is this score?

- Exam: 24 cases kept of 24 proposed; 0 discarded because their key facts were not found verbatim in the source; 0 'refusal' questions discarded because the documents could actually answer them. Types: {'paraphrase': 4, 'answerable': 10, 'multi_doc': 4, 'out_of_scope': 3, 'near_miss': 3}.
- Judge: deterministic checks decide; LLM judge (qwen/qwen3.8-27b) only arbitrates when some key facts are missing, and counts only if two votes with reversed fact order agree.
  Overrides by LLM judge: 3; unstable judgements: 1.
- The exam is generated from the same documents the agent retrieves from; it measures faithfulness to those documents, not real-world user satisfaction.
- Small models: agent `openai/gpt-oss-20b`, generator `openai/gpt-oss-20b`, judge `qwen/qwen3.8-27b`.
- intake: 5 questions, 100% reference real document terms

## Cost

158 LLM calls (30 cache hits), 129503 tokens, 65.59s of model time.

## Final agent rules

1. Answer ONLY from the CONTEXT passages (and tool results). Never use outside knowledge, guesses or common sense to fill gaps.
2. Cite the chunk ids you used in "citations", e.g. ["doc#3"]. Cite only passages that actually contain the answer.
3. If the CONTEXT does not contain the answer, set refused=true and use the refusal sentence. A partial answer must say what is missing.
4. Copy numbers, durations, names, codes and conditions exactly as written in the CONTEXT; never round or convert unless asked.
5. Politely decline these topics, even if the CONTEXT mentions them: legal advice; salary negotiation; pension investment advice; personal medical advice.
6. The documents do NOT cover: salary; pension. Say so instead of answering from general knowledge.
7. You only help with: annual leave; sick leave; bereavement leave; harassment; disciplinary process; company equipment use. Questions unrelated to these topics are out of scope: refuse them in one sentence.
8. Never provide information not directly supported by the provided policy context; if unsure, decline.  _(added iter 1: hallucination)_
9. When responding, always provide a complete answer that includes every required detail and a valid citation to the relevant policy document; do not omit any part of the answer.  _(added iter 1: prompt_defect)_

Retrieval: chunk 120/18 words, top_k 5, mode hybrid, rerank False, query_rewrite False

# ForgeAI quality report: hr_docs

## Verdict

**Final agent (v2) passes 16/22 generated test cases (73%).** With only 22 cases the 95% confidence interval is roughly **52% - 87%**, so treat it as an estimate, not a guarantee.
Dev split 75% (used by the optimizer) vs hold-out 67% (never inspected by it). Hold-out is close to dev: no obvious over-fitting.

## Scorecard per iteration

| Iter | Agent | Overall | Dev | Hold-out | Failures by class | Outcome |
|---|---|---|---|---|---|---|
| 0 | v1 | 13/22 (59%) | 62% | 50% | prompt_defect:6, hallucination:3 | baseline (as generated) |
| 1 | v2 | 16/22 (73%) | 75% | 67% | prompt_defect:5, hallucination:1 | accepted |
| 2 | v3 | 15/22 (68%) | 69% | 67% | prompt_defect:6, hallucination:1 | rolled back: dev 0.75->0.69, holdout 0.67->0.67 |
| 3 | v3 | 15/22 (68%) | 69% | 67% | prompt_defect:6, hallucination:1 | rolled back: dev 0.75->0.69, holdout 0.67->0.67 |

By case type (final): answerable 5/8, multi_doc 3/4, near_miss 2/3, out_of_scope 3/3, paraphrase 3/4

## Change log (what the optimizer changed and why)

- **Iter 1 / hallucination / rule** (kept; overall 59% -> 73%): [f1h] Never provide information not directly supported by the provided context; if unsure, decline.  (LLM-written rule passed leakage checks)  
  targeted cases: par-c8f28c
- **Iter 1 / prompt_defect / rule** (kept; overall 59% -> 73%): [f1p] When responding, always provide a complete answer that includes every required detail and a valid citation to the relevant policy document; do not omit any part of the requested information.  (LLM-written rule passed leakage checks)  
  targeted cases: par-823bed, ans-f17235, ans-cab7c7, ans-841b70, mul-a896e4
- **Iter 2 / prompt_defect / rule** (ROLLED BACK; overall 73% -> 68%): [f2p] When responding, always provide a complete answer that includes every required detail and a citation to the relevant policy document or section; do not omit any part of the requested information.  (LLM-written rule passed leakage checks)  
  targeted cases: par-823bed, ans-f17235, ans-cab7c7, mul-a896e4
- **Iter 3 / prompt_defect / rule** (ROLLED BACK; overall 73% -> 68%): [f3p] When responding, always provide a complete answer that includes every required detail and a citation to the relevant policy document or section; do not omit any part of the requested information.  (LLM-written rule passed leakage checks)  
  targeted cases: par-823bed, ans-f17235, ans-cab7c7, mul-a896e4

## What still fails, and why

- `par-823bed` (paraphrase, dev) **prompt_defect**: "If I see a colleague being treated unfairly, how can I report it and how long will it take for the company to look into it?"  
  agent said: "You can raise concerns with your line manager, with HR, or anonymously through the Ethics Hotline at ethics@meridian.example. Reports are acknowledged within 2 "  
  judge: facts missing from answer despite being retrieved
- `ans-f17235` (answerable, dev) **prompt_defect**: "What is the per diem for meals and incidentals in tier-1 cities, and how much is it reduced if a meal is provided by the host?"  
  agent said: "The per diem for meals and incidentals in tier‑1 cities is USD 60 per day, and it is reduced by USD 15 per meal if a meal is provided by the host."  
  judge: facts missing from answer despite being retrieved
- `ans-cab7c7` (answerable, dev) **prompt_defect**: "What is the maximum value of a gift that Meridian Shipping shore-based employees can accept from suppliers, customers or agents, and what must they do if a gift exceeds this value?"  
  agent said: "Meridian Shipping shore-based employees may accept gifts worth up to USD 50 from suppliers, customers or agents. If a gift exceeds this value, they must decline"  
  judge: facts missing from answer despite being retrieved
- `ans-4bbf8e` (answerable, holdout) **prompt_defect**: "What are the core working hours for Meridian Shipping shore-based employees?"  
  agent said: "The core working hours for Meridian Shipping shore-based employees are 09:30 to 17:30, Monday to Friday."  
  judge: facts missing from answer despite being retrieved
- `mul-a896e4` (multi_doc, dev) **prompt_defect**: "If an employee takes a 4‑day sick leave and receives a gift card from a supplier, what must the employee do according to company policy?"  
  agent said: "The employee must obtain a medical certificate for the 4‑day sick leave, as any sick leave of 3 or more consecutive days requires one. In addition, the employee"  
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

- Exam: 22 cases kept of 24 proposed; 2 discarded because their key facts were not found verbatim in the source; 0 'refusal' questions discarded because the documents could actually answer them. Types: {'paraphrase': 4, 'answerable': 8, 'multi_doc': 4, 'out_of_scope': 3, 'near_miss': 3}.
- Judge: deterministic checks decide; LLM judge (qwen/qwen3.8-27b) only arbitrates when some key facts are missing, and counts only if two votes with reversed fact order agree.
  Overrides by LLM judge: 4; unstable judgements: 1.
- The exam is generated from the same documents the agent retrieves from; it measures faithfulness to those documents, not real-world user satisfaction.
- Small models: agent `openai/gpt-oss-20b`, generator `openai/gpt-oss-20b`, judge `qwen/qwen3.8-27b`.
- intake: 5 questions, 100% reference real document terms

## Cost

191 LLM calls (93 cache hits), 101893 tokens, 59.58s of model time.

## Final agent rules

1. Answer ONLY from the CONTEXT passages (and tool results). Never use outside knowledge, guesses or common sense to fill gaps.
2. Cite the chunk ids you used in "citations", e.g. ["doc#3"]. Cite only passages that actually contain the answer.
3. If the CONTEXT does not contain the answer, set refused=true and use the refusal sentence. A partial answer must say what is missing.
4. Copy numbers, durations, names, codes and conditions exactly as written in the CONTEXT; never round or convert unless asked.
5. Politely decline these topics, even if the CONTEXT mentions them: legal advice; salary negotiation; pension investment advice; personal medical advice.
6. The documents do NOT cover: salary; pension. Say so instead of answering from general knowledge.
7. You only help with: annual leave; sick leave; bereavement leave; harassment; disciplinary process; company equipment use. Questions unrelated to these topics are out of scope: refuse them in one sentence.
8. Never provide information not directly supported by the provided context; if unsure, decline.  _(added iter 1: hallucination)_
9. When responding, always provide a complete answer that includes every required detail and a valid citation to the relevant policy document; do not omit any part of the requested information.  _(added iter 1: prompt_defect)_

Retrieval: chunk 120/18 words, top_k 5, mode hybrid, rerank False, query_rewrite False

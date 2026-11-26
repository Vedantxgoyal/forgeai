# ForgeAI quality report: hr_docs

## Verdict

**Final agent (v1) passes 20/24 generated test cases (83%).** With only 24 cases the 95% confidence interval is roughly **64% - 93%**, so treat it as an estimate, not a guarantee.
Dev split 83% (used by the optimizer) vs hold-out 83% (never inspected by it). Hold-out is close to dev: no obvious over-fitting.

## Scorecard per iteration

| Iter | Agent | Overall | Dev | Hold-out | Failures by class | Outcome |
|---|---|---|---|---|---|---|
| 0 | v1 | 20/24 (83%) | 83% | 83% | prompt_defect:3, hallucination:1 | baseline (as generated) |
| 1 | v2 | 20/24 (83%) | 83% | 83% | prompt_defect:3, hallucination:1 | no improvement; kept previous agent |

By case type (final): ambiguous 2/2, answerable 7/8, multi_doc 4/4, near_miss 2/3, out_of_scope 3/3, paraphrase 2/4

## Change log (what the optimizer changed and why)

- **Iter 1 / hallucination / rule** (ROLLED BACK; overall 83% -> 83%): [f1h] Never answer questions about salary, pension, or any topic not explicitly covered in the provided policy documents; if the information is not in the context, politely decline.  (LLM-written rule passed leakage checks)  
  targeted cases: nea-650da6
- **Iter 1 / prompt_defect / rule** (ROLLED BACK; overall 83% -> 83%): [f1p] Provide a complete answer including all required policy details and cite the specific policy sections for every factual claim.  (LLM-written rule passed leakage checks)  
  targeted cases: par-69dc45, ans-703ddf

## What still fails, and why

- `par-693b10` (paraphrase, holdout) **prompt_defect**: "How many days of holiday can I carry over to the next year?"  
  agent said: "You may carry forward up to 10 unused annual leave days to the next year."  
  judge: facts missing from answer despite being retrieved
- `par-69dc45` (paraphrase, dev) **prompt_defect**: "How long does my manager have to approve my leave request?"  
  agent said: "Your manager must approve the leave request within 3 working days."  
  judge: judge votes disagreed under fact reordering; deterministic verdict kept; facts missing from answer despite being retrieved
- `ans-703ddf` (answerable, dev) **prompt_defect**: "How many days per year can staff work from another country?"  
  agent said: "Staff may work from another country for up to 20 days per year."  
  judge: facts missing from answer despite being retrieved
- `nea-650da6` (near_miss, dev) **hallucination**: "How many unused leave days can a part‑time employee carry over to the next year under the leave_policy?"  
  agent said: "A part‑time employee may carry forward up to 10 unused leave days to the next year."  
  judge: answered a question the documents cannot support

## Requirements and groundability

Brief: An assistant that answers HR policy questions for Meridian Shipping's shore-based staff: leave, conduct, and travel/expense rules. It should also tell staff what the policy says about salary and pension, and keep answers short and polite.

- **PARTIAL** `annual leave entitlement` (lexical coverage 0.67, LLM verdict yes) Provides concrete details on annual leave entitlement
- **PARTIAL** `sick leave procedures` (lexical coverage 0.67, LLM verdict yes) Provides concrete sick leave policy details
- **PARTIAL** `harassment reporting and related leave options` (lexical coverage 0.6, LLM verdict partial) Provides harassment reporting details but no specific leave options related to it
- **SUPPORTED** `travel expense per diem rates` (lexical coverage 0.75, LLM verdict yes) Provides specific per diem amounts for meals and incidentals
- **SUPPORTED** `booking business travel guidelines` (lexical coverage 0.75, LLM verdict yes) Provides concrete booking guidelines

## Tools

Chosen: none (no tool needed for this brief)

## How trustworthy is this score?

- Exam: 24 cases kept of 32 proposed; 8 discarded because their key facts were not found verbatim in the source; 0 'refusal' questions discarded because the documents could actually answer them. Types: {'answerable': 8, 'paraphrase': 4, 'multi_doc': 4, 'ambiguous': 2, 'out_of_scope': 3, 'near_miss': 3}.
- Judge: deterministic checks decide; LLM judge (qwen/qwen3.8-27b) only arbitrates when some key facts are missing, and counts only if two votes with reversed fact order agree.
  Overrides by LLM judge: 4; unstable judgements: 1.
- Output contract: 0 answer(s) exceeded the word limit of 90 (reported, not scored).
- The exam is generated from the same documents the agent retrieves from; it measures faithfulness to those documents, not real-world user satisfaction.
- Configured models: agent `openai/gpt-oss-120b`, generator `openai/gpt-oss-120b`, judge `qwen/qwen3.8-27b`.
- intake: 3 questions, 100% reference real document terms

## Cost

120 LLM calls (120 cache hits), 0 tokens, 0.0s of model time.

## Final agent rules

1. Answer ONLY from the CONTEXT passages (and tool results). Never use outside knowledge, guesses or common sense to fill gaps.
2. Cite the chunk ids you used in "citations", e.g. ["doc#3"]. Cite only passages that actually contain the answer.
3. If the CONTEXT does not contain the answer, set refused=true and use the refusal sentence. A partial answer must say what is missing.
4. Copy numbers, durations, names, codes and conditions exactly as written in the CONTEXT; never round or convert unless asked.
5. If a question could mean more than one thing in the CONTEXT, either answer each meaning briefly and label it, or ask which one is meant.
6. Politely decline these topics, even if the CONTEXT mentions them: salary information; pension information.
7. You only help with: annual leave entitlement; sick leave procedures; harassment reporting and related leave options; travel expense per diem rates; booking business travel guidelines. Questions unrelated to these topics are out of scope: refuse them in one sentence.

Retrieval: chunk 120/18 words, top_k 5, mode hybrid, rerank False, query_rewrite False

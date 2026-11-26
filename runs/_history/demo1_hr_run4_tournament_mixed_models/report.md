# ForgeAI quality report: hr_docs

## Verdict

**Final agent (v1) passes 22/24 generated test cases (92%).** With only 24 cases the 95% confidence interval is roughly **74% - 98%**, so treat it as an estimate, not a guarantee.
Dev split 89% (used by the optimizer) vs hold-out 100% (never inspected by it). Hold-out is close to dev: no obvious over-fitting.

## Scorecard per iteration

| Iter | Agent | Overall | Dev | Hold-out | Failures by class | Outcome |
|---|---|---|---|---|---|---|
| 0 | v1 | 22/24 (92%) | 89% | 100% | retrieval_miss:2 | baseline (as generated) |
| 1 | v2 | 21/24 (88%) | 89% | 83% | prompt_defect:2, hallucination:1 | no improvement; kept previous agent | stopped: iteration 2 could not finish (QuotaExhausted); keeping the best agent so far |

By case type (final): ambiguous 0/2, answerable 8/8, multi_doc 4/4, near_miss 3/3, out_of_scope 3/3, paraphrase 4/4

## Prompt tournament (development cases only)

| Candidate | Passed | Prompt words | Result |
|---|---|---|---|
| as-generated | 7/10 | 60 |  |
| quote-first | 6/10 | 79 |  |
| checklist | 8/10 | 74 | **winner** |

Ties keep the unmodified prompt. With this few cases a one-case lead is weak evidence.

## Change log (what the optimizer changed and why)

- **Iter 1 / retrieval_miss / retrieval** (ROLLED BACK; overall 92% -> 88%): top_k 5 -> 8 (answer may sit just below the cut-off)  
  targeted cases: amb-f2b83b, amb-066fc0

## What still fails, and why

- `amb-f2b83b` (ambiguous, dev) **retrieval_miss**: "What is the maximum number of days allowed for this situation?"  
  agent said: "Maximum days per policy:
- Annual leave carry‑forward: up to 10 days (expires 31 Mar next year) ["leave_policy::0001"].
- Paid bereavement leave for spouse/chil"  
  judge: -
- `amb-066fc0` (ambiguous, dev) **retrieval_miss**: "How many days of leave can be taken for a personal emergency?"  
  agent said: "Up to 3 days of emergency leave may be approved per year for urgent personal matters such as a house fire or a family member’s hospitalisation."  
  judge: -

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

- Exam: 24 cases kept of 24 proposed; 0 discarded because their key facts were not found verbatim in the source; 0 'refusal' questions discarded because the documents could actually answer them. Types: {'answerable': 8, 'paraphrase': 4, 'multi_doc': 4, 'ambiguous': 2, 'out_of_scope': 3, 'near_miss': 3}.
- Judge: deterministic checks decide; LLM judge (qwen/qwen3.8-27b) only arbitrates when some key facts are missing, and counts only if two votes with reversed fact order agree.
  Overrides by LLM judge: 5; unstable judgements: 0.
- Output contract: 0 answer(s) exceeded the word limit of 90 (reported, not scored).
- The exam is generated from the same documents the agent retrieves from; it measures faithfulness to those documents, not real-world user satisfaction.
- Small models: agent `openai/gpt-oss-20b`, generator `openai/gpt-oss-20b`, judge `qwen/qwen3.8-27b`.
- intake: 5 questions, 100% reference real document terms
- MODEL SUBSTITUTION: openai/gpt-oss-20b -> openai/gpt-oss-120b for 122 call(s) because the configured model was unavailable
- MODEL SUBSTITUTION: qwen/qwen3.8-27b -> openai/gpt-oss-120b for 59 call(s) because the configured model was unavailable

## Cost

229 LLM calls (52 cache hits), 177873 tokens, 112.43s of model time.

## Final agent rules

1. Answer ONLY from the CONTEXT passages (and tool results). Never use outside knowledge, guesses or common sense to fill gaps.
2. Cite the chunk ids you used in "citations", e.g. ["doc#3"]. Cite only passages that actually contain the answer.
3. If the CONTEXT does not contain the answer, set refused=true and use the refusal sentence. A partial answer must say what is missing.
4. Copy numbers, durations, names, codes and conditions exactly as written in the CONTEXT; never round or convert unless asked.
5. If a question could mean more than one thing in the CONTEXT, either answer each meaning briefly and label it, or ask which one is meant.
6. Politely decline these topics, even if the CONTEXT mentions them: legal advice; salary negotiation; pension investment advice; personal medical advice.
7. The documents do NOT cover: salary; pension. Say so instead of answering from general knowledge.
8. You only help with: annual leave; sick leave; bereavement leave; harassment; disciplinary process; company equipment use. Questions unrelated to these topics are out of scope: refuse them in one sentence.

Retrieval: chunk 120/18 words, top_k 5, mode hybrid, rerank False, query_rewrite False

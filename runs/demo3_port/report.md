# ForgeAI quality report: port_docs

## Verdict

**Final agent (v1) passes 15/20 generated test cases (75%).** With only 20 cases the 95% confidence interval is roughly **53% - 89%**, so treat it as an estimate, not a guarantee.
Dev split 73% (used by the optimizer) vs hold-out 80% (never inspected by it). Hold-out is close to dev: no obvious over-fitting.

## Scorecard per iteration

| Iter | Agent | Overall | Dev | Hold-out | Failures by class | Outcome |
|---|---|---|---|---|---|---|
| 0 | v1 | 15/20 (75%) | 73% | 80% | prompt_defect:5 | baseline (as generated) |
| 1 | v2 | 13/20 (65%) | 60% | 80% | prompt_defect:6, wrong_refusal:1 | rolled back: dev 0.73->0.60, holdout 0.80->0.80 |

By case type (final): answerable 9/11, multi_doc 0/1, near_miss 3/3, out_of_scope 2/2, paraphrase 1/3

## Change log (what the optimizer changed and why)

- **Iter 1 / prompt_defect / rule** (ROLLED BACK; overall 75% -> 65%): [f1p] Ensure all answers are supported by relevant information from the provided context, and provide sufficient details to facilitate accurate decision-making.  (LLM-written rule passed leakage checks)  
  targeted cases: par-6108d6, par-0204c9, ans-977469, mul-e13445

## What still fails, and why

- `par-6108d6` (paraphrase, dev) **prompt_defect**: "How many tugboats should I have on board if my ship is really big?"  
  agent said: "at least 2 tugs"  
  judge: LLM judge unavailable; deterministic verdict kept; facts missing from answer despite being retrieved
- `ans-ac3b4b` (answerable, holdout) **prompt_defect**: "What is the minimum time before arrival that dangerous cargo must be declared?"  
  agent said: "48 hours before arrival"  
  judge: LLM judge unavailable; deterministic verdict kept; facts missing from answer despite being retrieved
- `par-0204c9` (paraphrase, dev) **prompt_defect**: "What should I do with my ship if it starts to blow strongly?"  
  agent said: "Stop cargo operations and consider tug assistance if wind speed exceeds 40 km/h."  
  judge: LLM judge unavailable; deterministic verdict kept; facts missing from answer despite being retrieved
- `ans-977469` (answerable, dev) **prompt_defect**: "What is the minimum wind speed at which tug assistance becomes mandatory?"  
  agent said: "40 km/h"  
  judge: facts missing from answer despite being retrieved
- `mul-e13445` (multi_doc, dev) **prompt_defect**: "What are the requirements for crew shore passes in Rotterdam and Singapore?"  
  agent said: "In Rotterdam, crew must return on board at least 2 hours before departure. In Singapore, shore passes are required for all crew going ashore, with a return requ"  
  judge: LLM judge unavailable; deterministic verdict kept; facts missing from answer despite being retrieved

## Requirements and groundability

Brief: An assistant for vessel masters planning port calls: it answers questions from our Rotterdam and Singapore port guides, and checks the current weather at the port to say whether operations are within the weather limits.

- **SUPPORTED** `Pre-arrival Notice` (lexical coverage 1.0, LLM verdict yes) Pre-arrival notification and declaration times are specified for both Rotterdam and Singapore ports.
- **SUPPORTED** `Pilotage` (lexical coverage 1.0, LLM verdict yes) Pilotage requirements and procedures are specified for certain vessel types and ports.
- **SUPPORTED** `Berthing and Mooring` (lexical coverage 1.0, LLM verdict yes) Specific guidelines for vessel size and wind speed requirements during cargo operations at berths.

## Tools

Chosen: `weather` (because: "it checks the current weather at the port to say whether operations are within the weather limits.")
- dropped `csv_lookup`: unavailable: no tabular files in the corpus

## How trustworthy is this score?

- Exam: 20 cases kept of 50 proposed; 36 discarded because their key facts were not found verbatim in the source; 0 'refusal' questions discarded because the documents could actually answer them. Types: {'paraphrase': 3, 'answerable': 11, 'multi_doc': 1, 'out_of_scope': 2, 'near_miss': 3}.
- Judge: deterministic checks decide; LLM judge (llama3.2:3b) only arbitrates when some key facts are missing, and counts only if two votes with reversed fact order agree.
  Overrides by LLM judge: 0; unstable judgements: 0.
- **8 case(s) are fill-in-the-blank cases built without the model**, because it could not produce enough verified ones. They are easier than model-written questions, so read the score with that in mind.
- Output contract: 0 answer(s) exceeded the word limit of 90 (reported, not scored).
- **Warning:** judge model and agent model are the same model, so self-preference bias is possible. Deterministic checks limit but do not remove it.
- The exam is generated from the same documents the agent retrieves from; it measures faithfulness to those documents, not real-world user satisfaction.
- Configured models: agent `llama3.2:3b`, generator `llama3.2:3b`, judge `llama3.2:3b`.
- intake: 3 questions, 100% reference real document terms

## Cost

172 LLM calls (172 cache hits), 0 tokens, 0.0s of model time.

## Final agent rules

1. Answer ONLY from the CONTEXT passages (and tool results). Never use outside knowledge, guesses or common sense to fill gaps.
2. In "citations", list the ids of the passages you used, copied exactly from the square brackets that start each CONTEXT passage. Cite only passages that actually contain the answer.
3. If the CONTEXT does not contain the answer, set refused=true and use the refusal sentence. A partial answer must say what is missing.
4. Copy numbers, durations, names, codes and conditions exactly as written in the CONTEXT; never round or convert unless asked.
5. If a question could mean more than one thing in the CONTEXT, either answer each meaning briefly and label it, or ask which one is meant.
6. You only help with: Pre-arrival Notice; Pilotage; Berthing and Mooring. Questions unrelated to these topics are out of scope: refuse them in one sentence.

Retrieval: chunk 120/18 words, top_k 5, mode hybrid, rerank False, query_rewrite False

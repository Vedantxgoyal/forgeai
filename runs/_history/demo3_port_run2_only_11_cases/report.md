# ForgeAI quality report: port_docs

## Verdict

**Final agent (v1) passes 10/11 generated test cases (91%).** With only 11 cases the 95% confidence interval is roughly **62% - 98%**, so treat it as an estimate, not a guarantee.
Dev split 100% (used by the optimizer) vs hold-out 67% (never inspected by it). A large dev/hold-out gap suggests the fixes may be tuned to the dev cases.

## Scorecard per iteration

| Iter | Agent | Overall | Dev | Hold-out | Failures by class | Outcome |
|---|---|---|---|---|---|---|
| 0 | v1 | 10/11 (91%) | 100% | 67% | prompt_defect:1 | baseline (as generated) | stopped: no dev failures remain |

By case type (final): answerable 3/3, multi_doc 2/3, near_miss 3/3, out_of_scope 2/2

## Change log (what the optimizer changed and why)

- No changes were needed or possible.

## What still fails, and why

- `mul-ed0a14` (multi_doc, holdout) **prompt_defect**: "What is the minimum advance notice required to request a pilot in Singapore and Rotterdam ports?"  
  agent said: "In Singapore, a pilot must be requested at least 12 hours in advance. In Rotterdam, a pilot must be requested 6 hours before the estimated time of arrival."  
  judge: facts missing from answer despite being retrieved

## Requirements and groundability

Brief: An assistant for vessel masters planning port calls: it answers questions from our Rotterdam and Singapore port guides, and checks the current weather at the port to say whether operations are within the weather limits.

- **SUPPORTED** `Weather Limits` (lexical coverage 1.0, LLM verdict yes) Provides specific wind speed limits for operations
- **SUPPORTED** `Crew Shore Leave` (lexical coverage 1.0, LLM verdict yes) Specifies shore pass requirement and return time for crew shore leave.
- **SUPPORTED** `Pre‑arrival Notice` (lexical coverage 1.0, LLM verdict yes) Provides specific pre‑arrival notice timing requirements
- **SUPPORTED** `Pilotage` (lexical coverage 1.0, LLM verdict yes) Provides concrete pilotage requirements
- **SUPPORTED** `Berthing and Mooring` (lexical coverage 1.0, LLM verdict yes) Provides specific mooring and tug requirements.
- **SUPPORTED** `Anchorage` (lexical coverage 1.0, LLM verdict yes) Provides specific anchoring rules.

## Tools

Chosen: `weather` (because: "checks the current weather against each port's limits")

## How trustworthy is this score?

- Exam: 11 cases kept of 11 proposed; 0 discarded because their key facts were not found verbatim in the source; 0 'refusal' questions discarded because the documents could actually answer them. Types: {'answerable': 3, 'multi_doc': 3, 'out_of_scope': 2, 'near_miss': 3}.
- Judge: deterministic checks decide; LLM judge (qwen/qwen3.8-27b) only arbitrates when some key facts are missing, and counts only if two votes with reversed fact order agree.
  Overrides by LLM judge: 1; unstable judgements: 0.
- The exam is generated from the same documents the agent retrieves from; it measures faithfulness to those documents, not real-world user satisfaction.
- Small models: agent `openai/gpt-oss-120b`, generator `openai/gpt-oss-120b`, judge `qwen/qwen3.8-27b`.
- intake: 3 questions, 100% reference real document terms
- WARNING: only 11 verified cases could be generated (<20 target); score is less reliable.

## Cost

34 LLM calls (0 cache hits), 26434 tokens, 21.09s of model time.

## Final agent rules

1. Answer ONLY from the CONTEXT passages (and tool results). Never use outside knowledge, guesses or common sense to fill gaps.
2. Cite the chunk ids you used in "citations", e.g. ["doc#3"]. Cite only passages that actually contain the answer.
3. If the CONTEXT does not contain the answer, set refused=true and use the refusal sentence. A partial answer must say what is missing.
4. Copy numbers, durations, names, codes and conditions exactly as written in the CONTEXT; never round or convert unless asked.
5. You only help with: Weather Limits; Crew Shore Leave; Pre‑arrival Notice; Pilotage; Berthing and Mooring; Anchorage. Questions unrelated to these topics are out of scope: refuse them in one sentence.

Retrieval: chunk 120/18 words, top_k 5, mode hybrid, rerank False, query_rewrite False

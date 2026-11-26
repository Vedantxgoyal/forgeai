# ForgeAI quality report: port_docs

## Verdict

**Final agent (v3) passes 13/20 generated test cases (65%).** With only 20 cases the 95% confidence interval is roughly **43% - 82%**, so treat it as an estimate, not a guarantee.
Dev split 67% (used by the optimizer) vs hold-out 60% (never inspected by it). Hold-out is close to dev: no obvious over-fitting.

## Scorecard per iteration

| Iter | Agent | Overall | Dev | Hold-out | Failures by class | Outcome |
|---|---|---|---|---|---|---|
| 0 | v1 | 11/20 (55%) | 53% | 60% | prompt_defect:6, retrieval_miss:1, hallucination:2 | baseline (as generated) |
| 1 | v2 | 12/20 (60%) | 60% | 60% | hallucination:3, retrieval_miss:1, prompt_defect:4 | accepted |
| 2 | v3 | 13/20 (65%) | 67% | 60% | hallucination:3, retrieval_miss:1, prompt_defect:3 | accepted |

By case type (final): answerable 11/14, multi_doc 0/1, out_of_scope 2/2, paraphrase 0/3

## Change log (what the optimizer changed and why)

- **Iter 1 / hallucination / rule** (kept; overall 55% -> 60%): [f1h] Never provide information that is not verifiably supported by official port guides, weather reports, or other credible sources.  (LLM-written rule passed leakage checks)  
  targeted cases: ans-059fdb
- **Iter 1 / prompt_defect / rule** (kept; overall 55% -> 60%): [f1p] All answers must include a clear reference to relevant official sources or industry standards for accuracy and reliability.  (LLM-written rule passed leakage checks)  
  targeted cases: par-a7a5a7, ans-ac3b4b, ans-66bcde, par-2178ac, ans-977469, mul-e13445
- **Iter 2 / hallucination / rule** (kept; overall 60% -> 65%): [f2h] Never provide information that is not verifiably supported by official port guides, weather reports, or reputable maritime sources.  (LLM-written rule passed leakage checks)  
  targeted cases: par-a7a5a7, ans-059fdb
- **Iter 2 / prompt_defect / rule** (kept; overall 60% -> 65%): [f2p] Provide all relevant details and supporting evidence for answers to ensure accuracy and reliability in port guide information.  (LLM-written rule passed leakage checks)  
  targeted cases: par-2178ac, ans-977469, mul-e13445, clz-fe6004

## What still fails, and why

- `par-a7a5a7` (paraphrase, dev) **hallucination**: "How many tugboats should I use if my ship is really big?"  
  agent said: "at least 2 tugs"  
  judge: LLM judge (2 agreeing votes) flagged unsupported claims; answer support 1.00
- `par-d3e0bb` (paraphrase, holdout) **retrieval_miss**: "What should I do when it starts to blow strongly?"  
  agent said: "Stop cargo operations and prepare for mooring assistance if wind speed exceeds 40 km/h, or seek alternative anchorage if wind speed exceeds 50 km/h."  
  judge: LLM judge unavailable; deterministic verdict kept
- `ans-87ba29` (answerable, holdout) **hallucination**: "What is the VHF channel used for continuous listening watch on anchorages?"  
  agent said: "VHF channel 12"  
  judge: LLM judge (2 agreeing votes) flagged unsupported claims; answer support 1.00
- `par-2178ac` (paraphrase, dev) **prompt_defect**: "How far in advance should I tell them if I have something hazardous on my ship?"  
  agent said: "At least 48 hours before arrival, as per Singapore Port Guide [singapore_port_guide::0000] (section: 1. Pre-arrival Notice) and Rotterdam Port Guide [rotterdam_"  
  judge: LLM judge unavailable; deterministic verdict kept; facts missing from answer despite being retrieved
- `ans-059fdb` (answerable, dev) **hallucination**: "What is the purpose of a continuous listening watch on VHF channel 12?"  
  agent said: "To maintain communication with port authorities and other vessels in the designated anchorages."  
  judge: answer support 0.50
- `ans-977469` (answerable, dev) **prompt_defect**: "What is the minimum wind speed at which tug assistance becomes mandatory?"  
  agent said: "40 km/h"  
  judge: LLM judge unavailable; deterministic verdict kept; facts missing from answer despite being retrieved
- `mul-e13445` (multi_doc, dev) **prompt_defect**: "What are the requirements for crew shore passes in Rotterdam and Singapore?"  
  agent said: "In Rotterdam, shore passes are required for all crew going ashore and must be returned on board at least 2 hours before departure. In Singapore, shore passes ar"  
  judge: LLM judge unavailable; deterministic verdict kept; facts missing from answer despite being retrieved

## Requirements and groundability

Brief: An assistant for vessel masters planning port calls: it answers questions from our Rotterdam and Singapore port guides, and checks the current weather at the port to say whether operations are within the weather limits.

- **SUPPORTED** `cargo operations` (lexical coverage 1.0, LLM verdict yes) cargo operations details including vessel requirements and wind speed guidelines
- **SUPPORTED** `mooring` (lexical coverage 1.0, LLM verdict yes) Specific guidelines for mooring lines and tug assistance are provided.
- **SUPPORTED** `vessels` (lexical coverage 1.0, LLM verdict yes) Regulations for vessel size and pilotage requirements are specified.
- **PARTIAL** `pre-arrival notice` (lexical coverage 1.0, LLM verdict partial) Pre-arrival notice details are partially provided for Rotterdam and Singapore ports.
- **SUPPORTED** `weather limits` (lexical coverage 1.0, LLM verdict yes) Weather limits for port operations are specified in the guidelines.

## Tools

Chosen: `weather` (because: "An assistant for vessel masters planning port calls: it answers questions from our Rotterdam and Singapore port guides, and checks the current weather at the port to say whether operations are within the weather limits.")
- dropped `csv_lookup`: unavailable: no tabular files in the corpus
- dropped `calculator`: justification quote not found in brief/requirements (match 60): 'it answers questions whose numbers are stated directly in the documents.'

## How trustworthy is this score?

- Exam: 20 cases kept of 47 proposed; 33 discarded because their key facts were not found verbatim in the source; 0 'refusal' questions discarded because the documents could actually answer them. Types: {'paraphrase': 3, 'answerable': 14, 'multi_doc': 1, 'out_of_scope': 2}.
- Judge: deterministic checks decide; LLM judge (llama3.2:3b) only arbitrates when some key facts are missing, and counts only if two votes with reversed fact order agree.
  Overrides by LLM judge: 0; unstable judgements: 0.
- **9 case(s) are fill-in-the-blank cases built without the model**, because it could not produce enough verified ones. They are easier than model-written questions, so read the score with that in mind.
- Output contract: 0 answer(s) exceeded the word limit of 90 (reported, not scored).
- **Warning:** judge model and agent model are the same model, so self-preference bias is possible. Deterministic checks limit but do not remove it.
- The exam is generated from the same documents the agent retrieves from; it measures faithfulness to those documents, not real-world user satisfaction.
- Configured models: agent `llama3.2:3b`, generator `llama3.2:3b`, judge `llama3.2:3b`.
- intake: 0 questions, 0% reference real document terms

## Cost

208 LLM calls (86 cache hits), 107418 tokens, 5786.53s of model time.

## Final agent rules

1. Answer ONLY from the CONTEXT passages (and tool results). Never use outside knowledge, guesses or common sense to fill gaps.
2. In "citations", list the ids of the passages you used, copied exactly from the square brackets that start each CONTEXT passage. Cite only passages that actually contain the answer.
3. If the CONTEXT does not contain the answer, set refused=true and use the refusal sentence. A partial answer must say what is missing.
4. Copy numbers, durations, names, codes and conditions exactly as written in the CONTEXT; never round or convert unless asked.
5. If a question could mean more than one thing in the CONTEXT, either answer each meaning briefly and label it, or ask which one is meant.
6. You only help with: cargo operations; mooring; vessels; pre-arrival notice; weather limits. Questions unrelated to these topics are out of scope: refuse them in one sentence.
7. Never provide information that is not verifiably supported by official port guides, weather reports, or other credible sources.  _(added iter 1: hallucination)_
8. All answers must include a clear reference to relevant official sources or industry standards for accuracy and reliability.  _(added iter 1: prompt_defect)_
9. Never provide information that is not verifiably supported by official port guides, weather reports, or reputable maritime sources.  _(added iter 2: hallucination)_
10. Provide all relevant details and supporting evidence for answers to ensure accuracy and reliability in port guide information.  _(added iter 2: prompt_defect)_

Retrieval: chunk 120/18 words, top_k 5, mode hybrid, rerank False, query_rewrite False

# ForgeAI quality report: spares_docs

## Verdict

**Final agent (v1) passes 18/25 generated test cases (72%).** With only 25 cases the 95% confidence interval is roughly **52% - 86%**, so treat it as an estimate, not a guarantee.
Dev split 79% (used by the optimizer) vs hold-out 50% (never inspected by it). A large dev/hold-out gap suggests the fixes may be tuned to the dev cases.

## Scorecard per iteration

| Iter | Agent | Overall | Dev | Hold-out | Failures by class | Outcome |
|---|---|---|---|---|---|---|
| 0 | v1 | 18/25 (72%) | 79% | 50% | prompt_defect:6, hallucination:1 | baseline (as generated) |

By case type (final): ambiguous 1/2, answerable 3/3, multi_doc 3/4, near_miss 2/3, out_of_scope 3/3, paraphrase 3/4, tool 3/6

## Change log (what the optimizer changed and why)

- No changes were needed or possible.

## What still fails, and why

- `par-954e2f` (paraphrase, dev) **prompt_defect**: "Who has to sign off on a $5,000 purchase order?"  
  agent said: "The Superintendent must sign off a $5,000 purchase order."  
  judge: facts missing from answer despite being retrieved
- `mul-71c6fa` (multi_doc, holdout) **prompt_defect**: "If a vessel arrives in 8 days and the buyer wants to use express freight, what surcharge must the Superintendent approve and what is the maximum credit the buyer can claim for a 9‑day late delivery?"  
  agent said: "The Superintendent must approve an express freight surcharge of 12 % of the order value if the parts are sourced from OceanParts, or 20 % if sourced from NordMa"  
  judge: facts missing from answer despite being retrieved
- `amb-dce4ca` (ambiguous, dev) **prompt_defect**: "What is required for orders above a certain dollar amount?"  
  agent said: "For orders above USD 5,000, at least two quotes must be obtained unless the part is single‑source, and the single‑source justification must be recorded in the p"  
  judge: facts missing from answer despite being retrieved
- `nea-bbe5af` (near_miss, holdout) **hallucination**: "What is the warranty period for the new hull coating supplied by Oceanparts?"  
  agent said: "The warranty period for the new hull coating supplied by Oceanparts is 12 months from delivery."  
  judge: answered a question the documents cannot support
- `too-57b868` (tool, holdout) **prompt_defect**: "What is the exact difference in unit price usd between SP-1091 (Mechanical seal) and SP-1140 (Flame sensor)?"  
  agent said: "The unit price of SP-1091 (Mechanical seal) is $218.0, while the unit price of SP-1140 (Flame sensor) is $163.0. The exact difference is $55.0."  
  judge: answer support 0.79, numbers not in context: ['55']; wrong or unsupported value; tools used: ['csv_lookup']; expected |218 - 163| = 55
- `too-a8221e` (tool, dev) **prompt_defect**: "What is the exact difference in unit price usd between SP-1063 (Cylinder head gasket) and SP-1084 (Seawater pump impeller)?"  
  agent said: "The unit price of SP-1063 is $134.0, while SP-1084 is $346.0. The exact difference is $212.0."  
  judge: answer support 0.70, numbers not in context: ['212']; wrong or unsupported value; tools used: ['csv_lookup']; expected |134 - 346| = 212
- `too-8bd1f7` (tool, dev) **prompt_defect**: "What is the min order qty recorded for SP-1273 (Deck crane wire rope 20mm 100m)?"  
  agent said: "The minimum order quantity for SP-1273 is 1."  
  judge: answer support 0.50; wrong or unsupported value; tools used: ['csv_lookup']; expected min order qty = 1

## Requirements and groundability

Brief: A procurement assistant for ship superintendents and chief engineers that helps them find spare parts in our catalogue, check price, stock and lead time, compare the two suppliers' terms, work out order totals with discounts, and say who must approve a purchase.

- **SUPPORTED** `approval thresholds` (lexical coverage 1.0, LLM verdict yes) States specific approval thresholds for purchase orders.
- **SUPPORTED** `critical spares` (lexical coverage 1.0, LLM verdict yes) Provides specific rules and categories for critical spares
- **SUPPORTED** `urgent orders` (lexical coverage 1.0, LLM verdict yes) The text provides specific rules for urgent orders and express freight.
- **PARTIAL** `supplier terms comparison` (lexical coverage 0.67, LLM verdict yes) Provides specific payment terms for NordMarine
- **PARTIAL** `discount structure` (lexical coverage 0.5, LLM verdict yes) Provides specific discount percentages and order value thresholds.
- **SUPPORTED** `warranty period` (lexical coverage 1.0, LLM verdict yes) Warranty periods are explicitly stated for parts.
- **PARTIAL** `order total calculation` (lexical coverage 0.67, LLM verdict partial) Provides discount thresholds but not full total calculation details

## Tools

Chosen: `csv_lookup` (because: ""Assist ship superintendents and chief engineers in sourcing spare parts, checking prices, stock, lead times""), `calculator` (because: ""calculating order totals with discounts"")

## How trustworthy is this score?

- Exam: 25 cases kept of 29 proposed; 4 discarded because their key facts were not found verbatim in the source; 0 'refusal' questions discarded because the documents could actually answer them. Types: {'paraphrase': 4, 'answerable': 3, 'multi_doc': 4, 'ambiguous': 2, 'out_of_scope': 3, 'near_miss': 3, 'tool': 6}.
- Judge: deterministic checks decide; LLM judge (qwen/qwen3.8-27b) only arbitrates when some key facts are missing, and counts only if two votes with reversed fact order agree.
  Overrides by LLM judge: 5; unstable judgements: 0.
- Output contract: 0 answer(s) exceeded the word limit of 90 (reported, not scored).
- The exam is generated from the same documents the agent retrieves from; it measures faithfulness to those documents, not real-world user satisfaction.
- Configured models: agent `openai/gpt-oss-20b`, generator `openai/gpt-oss-20b`, judge `qwen/qwen3.8-27b`.
- intake: 5 questions, 100% reference real document terms

## Cost

86 LLM calls (86 cache hits), 0 tokens, 0.0s of model time.

## Final agent rules

1. Answer ONLY from the CONTEXT passages (and tool results). Never use outside knowledge, guesses or common sense to fill gaps.
2. Cite the chunk ids you used in "citations", e.g. ["doc#3"]. Cite only passages that actually contain the answer.
3. If the CONTEXT does not contain the answer, set refused=true and use the refusal sentence. A partial answer must say what is missing.
4. Copy numbers, durations, names, codes and conditions exactly as written in the CONTEXT; never round or convert unless asked.
5. If a question could mean more than one thing in the CONTEXT, either answer each meaning briefly and label it, or ask which one is meant.
6. You only help with: approval thresholds; critical spares; urgent orders; supplier terms comparison; discount structure; warranty period; order total calculation. Questions unrelated to these topics are out of scope: refuse them in one sentence.
7. For the price, stock or any attribute of a specific record, call csv_lookup first and use the exact value it returns.
8. Never do arithmetic yourself: call the calculator for every total, difference or percentage, then report its result.

Retrieval: chunk 120/18 words, top_k 5, mode hybrid, rerank False, query_rewrite False

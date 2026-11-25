# ForgeAI quality report: spares_docs

## Verdict

**Final agent (v1) passes 24/24 generated test cases (100%).** With only 24 cases the 95% confidence interval is roughly **86% - 100%**, so treat it as an estimate, not a guarantee.
Dev split 100% (used by the optimizer) vs hold-out 100% (never inspected by it). Hold-out is close to dev: no obvious over-fitting.

## Scorecard per iteration

| Iter | Agent | Overall | Dev | Hold-out | Failures by class | Outcome |
|---|---|---|---|---|---|---|
| 0 | v1 | 24/24 (100%) | 100% | 100% | none | baseline (as generated) | stopped: no dev failures remain |

By case type (final): answerable 10/10, multi_doc 4/4, near_miss 3/3, out_of_scope 3/3, paraphrase 4/4

## Change log (what the optimizer changed and why)

- No changes were needed or possible.

## What still fails, and why

Nothing failed on this exam. That does not mean the agent is perfect: the exam was generated from the same documents by a small model, so it can miss question styles real users will try.

## Requirements and groundability

Brief: A procurement assistant for ship superintendents and chief engineers that helps them find spare parts in our catalogue, check price, stock and lead time, compare the two suppliers' terms, work out order totals with discounts, and say who must approve a purchase.

- **PARTIAL** `spare parts catalogue lookup` (lexical coverage 0.5, LLM verdict yes) The text provides specific spare parts data including part numbers, descriptions, prices, and stock levels, which directly supports catalogue lookup queries.
- **SUPPORTED** `unit price and stock availability` (lexical coverage 0.75, LLM verdict yes) The text provides specific unit prices and stock quantities for multiple spare parts.
- **PARTIAL** `lead time and urgent order classification` (lexical coverage 0.8, LLM verdict partial) The text defines urgent order criteria and lead time reductions for express freight but does not provide a general classification system for all order types.
- **SUPPORTED** `supplier pricing and discount terms` (lexical coverage 1.0, LLM verdict yes) The text provides specific discount percentages, order value thresholds, and payment terms for two suppliers.
- **SUPPORTED** `returns and warranty conditions` (lexical coverage 1.0, LLM verdict yes) The text provides specific details on return windows, restocking fees, and warranty durations for different suppliers.
- **PARTIAL** `order total calculation` (lexical coverage 0.67, LLM verdict partial) The text provides specific volume discount thresholds and base price conditions but does not detail the full calculation method for the final order total including freight and taxes.
- **SUPPORTED** `internal approval thresholds` (lexical coverage 1.0, LLM verdict yes) The text explicitly defines specific monetary thresholds for internal approval by different roles and prohibits splitting orders to bypass them.

## Tools

Chosen: `csv_lookup` (because: "The assistant handles spare part lookups, price and stock verification"), `calculator` (because: "order total calculations with discounts")

## How trustworthy is this score?

- Exam: 24 cases kept of 24 proposed; 0 discarded because their key facts were not found verbatim in the source; 0 'refusal' questions discarded because the documents could actually answer them. Types: {'paraphrase': 4, 'answerable': 10, 'multi_doc': 4, 'out_of_scope': 3, 'near_miss': 3}.
- Judge: deterministic checks decide; LLM judge (qwen/qwen3.8-27b) only arbitrates when some key facts are missing, and counts only if two votes with reversed fact order agree.
  Overrides by LLM judge: 5; unstable judgements: 0.
- **Warning:** judge model and agent model are the same model, so self-preference bias is possible. Deterministic checks limit but do not remove it.
- The exam is generated from the same documents the agent retrieves from; it measures faithfulness to those documents, not real-world user satisfaction.
- Small models: agent `qwen/qwen3.8-27b`, generator `qwen/qwen3.8-27b`, judge `qwen/qwen3.8-27b`.
- intake: 5 questions, 100% reference real document terms

## Cost

67 LLM calls (67 cache hits), 0 tokens, 0.0s of model time.

## Final agent rules

1. Answer ONLY from the CONTEXT passages (and tool results). Never use outside knowledge, guesses or common sense to fill gaps.
2. Cite the chunk ids you used in "citations", e.g. ["doc#3"]. Cite only passages that actually contain the answer.
3. If the CONTEXT does not contain the answer, set refused=true and use the refusal sentence. A partial answer must say what is missing.
4. Copy numbers, durations, names, codes and conditions exactly as written in the CONTEXT; never round or convert unless asked.
5. Politely decline these topics, even if the CONTEXT mentions them: external financial settlement advice; non-procurement operational advice; advice for non-technical audiences.
6. You only help with: spare parts catalogue lookup; unit price and stock availability; lead time and urgent order classification; supplier pricing and discount terms; returns and warranty conditions; order total calculation; internal approval thresholds. Questions unrelated to these topics are out of scope: refuse them in one sentence.

Retrieval: chunk 120/18 words, top_k 5, mode hybrid, rerank False, query_rewrite False

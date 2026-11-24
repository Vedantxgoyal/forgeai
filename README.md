# ForgeAI — the agent that builds agents

ForgeAI takes a one-paragraph brief and a folder of documents and produces a tested RAG agent: requirements,
system prompt, retrieval config, tool selection, a verified eval set, a scored exam, up to 3 targeted
improvement rounds, and an honest quality report. Every stage is designed for a **small, imperfect open model**.

> **Design principle: distrust the pipeline.** No single LLM output is trusted. Every stage has a deterministic
> verifier, every score carries evidence, and the optimizer is judged on held-out cases it never saw.

## Run it

```powershell
pip install -e ".[dev]"
copy .env.example .env            # choose Ollama (local) or Groq (hosted open models)
forge ping                        # check the models respond
python demos/make_demo_docs.py    # builds the two demo corpora
forge run demos/hr_docs     --brief @demos/briefs/hr.txt     --out runs/demo1_hr
forge run demos/spares_docs --brief @demos/briefs/spares.txt --out runs/demo2_spares
forge chat runs/demo1_hr/agent.final.yaml demos/hr_docs --trace     # generic runner: works with ANY definition
forge run <any folder> --brief "…" -i --approve     # interview yourself, approve requirements before generation
pytest                            # offline tests, including a whole-factory run on a scripted fake model
```

## What happens in `forge run`

| # | Stage | What is distinctive | File |
|---|---|---|---|
| 1 | Intake | Questions are built from a deterministic corpus profile; a question that names nothing in the documents is rejected as *generic* and regenerated. The share of document-grounded questions is reported. | `factory/intake.py` |
| 2 | Groundability guard | Each requested topic is searched in the corpus. Lexical coverage (deterministic) + LLM verdict; the LLM can only *lower* a status. Unsupported topics become prompt rules and near-miss tests. | `factory/guard.py` |
| 3 | Agent generator | Prompt is **composed from named rules** (vetted grounding skeleton + domain rules), so the optimizer can patch one rule. A tool survives only if it is available for the corpus **and** justified by a quote that actually occurs in the brief; dropped tools are logged with reasons. | `factory/generator.py` |
| 4 | Eval generator | ≥20 cases from the documents. Answerable/paraphrase: every key fact must appear **verbatim** in the source chunk or the case is discarded. Refusal cases are discarded if the corpus can actually answer them. Multi-document cases need facts from two docs. Stratified **dev / hold-out** split. | `factory/evalgen.py` |
| 5 | Judge | Deterministic first: refusal detection, key-fact match, citation validity, groundedness (token + number support). The LLM only arbitrates missing facts, asked per-fact yes/no (verbosity), twice with reversed order (position bias), and only counts if both votes agree; judge model is separate (self-preference) and the report warns if it equals the agent model. | `factory/judge.py` |
| 6 | Critic–optimizer | Failure classes (`retrieval_miss`, `wrong_refusal`, `hallucination`, `prompt_defect`) come from evidence, e.g. *were the required facts present in the retrieved context?* Each class gets the smallest fix: a retrieval ladder (top_k → query rewrite → rerank → smaller chunks) or one new prompt rule that is rejected if it leaks test facts or copies a test question. Rolled back if dev or hold-out gets worse. | `factory/optimizer.py` |
| 7 | Report | Scorecard per iteration, change log with before/after, what still fails and why, Wilson 95% interval, judge-reliability stats, token cost. Never claims more than the evidence. | `factory/report.py` |

Artifacts per run: `00_brief.txt`, `01_corpus_profile.json`, `02_questions.json`, `02_requirements.json`,
`03_agent.v1.yaml`, `04_evals.json`, `05_iteration_N.json`, `agent.final.yaml`, `changelog.json`, `report.md`, `manifest.json`.

## Layout

```
forgeai/
  llm/        OpenAI-compatible client (Ollama/Groq), disk cache, token meter, JSON repair + schema retry + flagged fallback
  ingest/     PDF/DOCX/CSV/XLSX/MD/HTML loaders, corpus profiler, section-aware chunker
  retrieval/  dense + BM25 + RRF, optional cross-encoder rerank, per-hit trace
  tools/      csv_lookup, calculator (AST-safe), weather (open-meteo, keyless), current_date — each with a capability card
  agent/      generic runtime: loads any AgentDef + folder, tool loop, retrieval trace
  factory/    intake, guard, generator, evalgen, judge, optimizer, report, pipeline
  prompts/    every generation prompt as a versioned .md file
demos/        synthetic corpora + briefs + the script that builds them
runs/         committed artifacts of the demo runs
```

## Models

Everything runs on small open models through one OpenAI-compatible client, so Ollama (local) and Groq (hosted
Llama/Qwen) differ only in `.env`. On a CPU-only laptop a 3B model needs ~1 minute per call, which makes a full run
hours long; a hosted open model makes it minutes. Cache + `FORGE_SEED` make re-runs reproducible and resumable.
Use different model families for generator/agent and judge when you can (self-preference); the report states what was used.

## Honest limitations

- Exams are generated from the same documents the agent reads: they measure faithfulness to those documents, not user satisfaction.
- With ~20–24 cases the confidence interval is wide (reported). A small model can still mis-grade; deterministic checks bound, not remove, that risk.
- Scanned PDFs have no OCR (flagged at load time); the guard cannot reason about images.

## Prior work

The retrieval design (hybrid search, RRF fusion, cross-encoder reranking, retrieval tracing) is informed by my earlier
project **DocSage**. ForgeAI was written from scratch and adds requirement intake, groundability checks, agent generation,
verified eval generation, judging and self-optimisation, none of which DocSage had.

# Demo video script (target 6–7 minutes)

Record the screen with the terminal on the left and an editor/preview on the right. Keep the font large.
Everything below is already produced by the committed runs, so you can show artifacts instead of waiting for a live run.

## 0:00–0:40 — The idea (say it, show the README diagram/table)
"Most teams hand-build every RAG assistant. ForgeAI is the factory: give it a one-paragraph brief and a folder of
documents; it interviews you, checks the documents can support the brief, builds the agent, writes its own exam,
grades it, fixes only what failed, and gives back an honest report. I built it for small, imperfect models, so
the principle is: **distrust the pipeline**. Every LLM output has a deterministic check."

## 0:40–2:30 — Demo 1: HR policy assistant (no tools)
1. `forge inspect demos/hr_docs` — three PDFs, sections detected, chunk size chosen from the data.
2. Open `runs/demo1_hr/02_questions.json`: questions reference real headings; `grounded_share`.
3. Open `02_requirements.json`: **the brief asked for salary and pension; the documents say nothing → flagged UNSUPPORTED** and the agent is told to decline. "This is the groundability guard: the agent will not invent answers to fill the gap."
4. Open `03_agent.v1.yaml`: no tools — "an HR bot with a weather tool would be a defect". Show `dropped_rules`: the model's own domain rules were held back (evidence-gated prompt).
5. Open `04_evals.json`: 24 cases; point out `key_facts` copied verbatim from the source, refusal and near-miss cases, `split: holdout`.

## 2:30–4:30 — The scorecard and the optimizer (the honest part)
Open `runs/demo1_hr/report.md`:
- Scorecard table: baseline 75% → 88% after iteration 1; iterations 2 and 3 **rolled back** because they made it worse (iteration 3 caused 7 wrong refusals). "The loop is allowed to fail and undo itself."
- Change log: one rule per failure class, not a regenerated prompt; each logged with before/after score.
- "What still fails and why": three cases with causes. Confidence interval 69–96%. "A well-explained 88% beats a suspicious 100%."
- Judge section: deterministic checks decide; LLM only arbitrates with two votes in reversed order (position bias); different model family (self-preference); per-fact yes/no (verbosity).

## 4:30–5:45 — Demo 2: ship-spares procurement (very different)
1. `runs/demo2_spares/agent.final.yaml`: picks **csv_lookup + calculator**, with quoted justifications from the brief; nothing else.
2. `runs/demo2_spares/04_evals.json`: show a `tool` case — the expected total is computed in Python from the CSV.
3. Report: 23/24. Iteration 1 (bigger top_k) was rolled back. Say openly: the one remaining failure is likely my judge
   counting a list marker "1." as a number (see NOTE.md), fixed in code afterwards.
4. Live chat (`streamlit run app.py`, Chat tab, open the Trace panel):
   - "What is the total for 8 units of SP-1042?"  (lookup + arithmetic)
   - "Who must approve a purchase order of USD 7,840?"  (procedure document)
   - "How do I cook a steak?"  (refusal)

## 5:45–6:30 — Robustness + what I'd do next
- Unseen folder: `forge run demos/port_docs --brief "@demos/briefs/port.txt" --out runs/demo3_port` (should pick the weather tool).
- Bugs the real run exposed in my own pipeline (Unicode hyphens, over-specified test facts, guard false positives) — "I fixed the pipeline, not the scores" — see `runs/_history/`.
- Limits: exam is generated from the same docs; ~24 cases gives a wide interval; no OCR.
- Credit: retrieval design informed by my earlier project DocSage; ForgeAI itself written from scratch.

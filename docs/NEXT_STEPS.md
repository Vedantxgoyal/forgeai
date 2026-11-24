# Where we stopped (Wed 25 Nov) and what is left

Deadline: **Fri 27 Nov, 12:00 noon** (repo link + 3–8 min video + optional hosted link).

## Done
- Full factory: intake, guard, agent generator, eval generator, judge, optimizer, report, `forge run`, `forge chat`.
- 69 offline tests pass (`pytest`).
- **Demo 1 (HR, no tools) complete**: `runs/demo1_hr/` — 21/24 (88%), hold-out 86%, optimizer rolled back 2 bad iterations. Earlier pass kept in `runs/_history/`.
- Demo 2 (ship spares, csv_lookup + calculator) was **mid-run** (baseline exam) when we stopped. Agent definition and evals were generated.
- `docs/DEMO_SCRIPT.md` = video outline.

## IMPORTANT finding (demo 2)
Demo 2 finished at **24/24 (100%)** with zero optimizer changes. OceanAI says a suspicious 100% is worse than an
explained 78%, and this exam is too easy: every case is generated from ONE passage or a pair, so **no case needs
csv_lookup or the calculator** and the agent's tools are never tested. Do this first tomorrow:
- Add a `tool` case type in `factory/evalgen.py`: for corpora with tables, build cases that need a row lookup
  (price/stock/lead time of a named part) and a calculation (qty x unit price, minus the supplier's volume discount).
  Compute the expected value deterministically in Python from the CSV + discount text (not from the LLM), so
  `key_facts` is a number. The judge already compares numbers by value.
- Add harder cases (conflicting facts across suppliers, thresholds just under/over a limit).
- Re-run demo 2; expect failures; let the optimizer work. Report whatever honestly comes out.
- Also: stronger judge/agent split (use gpt-oss-20b for agent and qwen as judge once Groq's daily cap resets).

## Do next (in this order)
1. Check whether `runs/demo2_spares/report.md` exists. If yes, read it and fix anything suspicious.
   If not (laptop slept/process died), re-run — finished LLM calls are cached, so it resumes quickly:
   ```powershell
   cd D:\Projects\FORGEAI\forgeai
   $env:FORGE_GEN_MODEL="qwen/qwen3.8-27b"; $env:FORGE_AGENT_MODEL="qwen/qwen3.8-27b"; $env:FORGE_JUDGE_MODEL="qwen/qwen3.8-27b"; $env:HF_HUB_OFFLINE="1"
   forge run demos/spares_docs --brief "@demos/briefs/spares.txt" --out runs/demo2_spares --cases 24 --workers 2
   ```
   Reason for Qwen: Groq's free daily token cap (200k) for `openai/gpt-oss-20b` was used up. The daily cap resets,
   so tomorrow you can use the default `.env` models again if you prefer (judge differs from agent = no self-preference warning).
2. Third, unseen brief as a robustness check (any small folder of docs; e.g. an IT-helpdesk FAQ). Save under `runs/demo3_*`.
3. README: add results table, model note (demo 1 gpt-oss-20b + qwen judge; demo 2 qwen only), architecture diagram.
4. Record the video following `docs/DEMO_SCRIPT.md`; try `forge chat runs/demo2_spares/agent.final.yaml demos/spares_docs --trace`.
5. Push to GitHub (create an empty repo, then `git remote add origin <url>; git push -u origin main`). `.env` is git-ignored (holds the Groq key) — never commit it.
6. Optional: Streamlit UI + free hosting (only if everything above is done).

## Gotchas
- Groq free tier rate-limits (429); the client retries up to 8 times. If a run dies with RateLimitError, just re-run.
- `.env` currently points to Groq. Local Ollama (3B) is too slow on this CPU-only laptop.
- On Windows, if `rm -rf runs/...` says "busy", close terminals sitting in that folder first.

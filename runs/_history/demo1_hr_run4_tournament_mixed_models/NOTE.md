# Provenance and how to read the 22/24

**Models.** Configured: agent and generator `openai/gpt-oss-20b`, judge `qwen/qwen3.8-27b`. Both ran out of daily quota,
and the fallback served 181 calls with `openai/gpt-oss-120b` (122 for the agent/generator model, 59 for the judge).
So **for part of this run the agent and the judge were the same model**, and self-preference bias is possible. The
report lists the substitutions but its "How trustworthy" section does not warn about the shared model; the code does now.

**Both remaining failures are most likely bad test cases, not agent mistakes.**
- `amb-066fc0` asks about leave "for a personal emergency". Only emergency leave fits, so the agent's answer is correct
  and the question was never ambiguous.
- `amb-f2b83b` asks about "this situation" without saying which. The agent listed several limits, which is reasonable.
The generator now rejects ambiguous questions with dangling references or with words that only one passage matches.
The score has **not** been adjusted.

**Stopped early.** Iteration 1 (larger top-k) did not help and was rejected. Iteration 2 could not finish because every
model in the fallback chain had spent its quota, so the baseline agent (v1) is the final one. Because iteration 1 and
the prompt tournament are the only changes tried, this run says little about the optimizer.

**Tournament.** The `checklist` prompt won 8/10 against 7/10 on development cases. A one-case lead is weak evidence.

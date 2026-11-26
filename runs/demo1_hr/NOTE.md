# Provenance and how to read the 20/24

**Models.** Agent and generator `openai/gpt-oss-120b`, judge `qwen/qwen3.8-27b` (Groq free tier). One model per role for the
whole run: no fallback, no substitutions, no outages, no invalid agent outputs.

**Code version.** Commit "Reject test questions that refer to the generator's passages". Later fixes (passage layout shown
to the agent, citation wording, weak-model robustness) are not in this run.

**Loop.** The run was capped at two improvement rounds; the free tier's refill rate allowed one before the deadline, and the
artifacts were assembled from the cached model calls of that same run. Round 1 added two prompt rules, fixed one case
(`ans-703ddf`), broke another (`mul-1b427c`), and was rejected for no net gain, so the generated agent (v1) is the final
one.

**The four failures, read by hand.**
- `par-693b10`, `par-69dc45`, `ans-703ddf`: the agent's answer to the question asked is correct. Each test case also
  requires a detail the question did not ask for (an expiry date, who approves, an approval condition). These are most
  likely weaknesses of the generated tests.
- `nea-650da6`: a real mistake. Asked about part-time employees, the agent repeated the general rule although the documents
  say nothing about part-time staff.

The score has not been adjusted for the likely test weaknesses.

# Provenance and how to read the 24/24
Models: agent/generator qwen/qwen3.8-27b, judge openai/gpt-oss-120b (Groq free tier). Many LLM calls were served from
the disk cache of the previous run (same prompts), so this run finished quickly.

24/24 does NOT mean the agent is flawless (95% interval 86-100%). Weaknesses of this exam that a reviewer should know:
- All 4 multi-document cases passed through the LLM judge's override (their key facts are whole sentences, so exact
  matching fails on any rewording). The answers were spot-checked by reading them, but the pass rests on the LLM judge.
- Tool cases cover lookup, multiplication and difference. None applies a supplier volume discount or an approval
  threshold to a computed total, which is the hardest thing a real user would ask.
- Questions are generated from the same documents the agent reads.

**Code version.** This run was produced by an earlier version of the code: it has no ambiguous cases and uses the same
output contract as every other agent of that time. A re-run on the current code stopped during its first exam because
the free tier's daily quota was spent, so this complete run is kept.

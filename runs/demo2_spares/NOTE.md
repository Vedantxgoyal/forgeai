# Provenance and known issues of this run
Models: agent/generator qwen/qwen3.8-27b, judge openai/gpt-oss-120b (Groq free tier).

Read the score (23/24) with these two caveats, both found by reviewing this report and fixed in code afterwards:
1. The single remaining "hallucination" (par-f06b90) is very likely a JUDGE FALSE POSITIVE: the judge counted the
   list marker "1." in the answer as a number missing from the context.
2. Iterations 2 and 3 were kept although neither improved any score (dev and hold-out unchanged), and the rule added
   in iteration 3 partly conflicts with the calculator rule. The optimizer now keeps a change only if a score improves.
The run was not repeated because the free tier's daily token limit was reached. Re-run to confirm.

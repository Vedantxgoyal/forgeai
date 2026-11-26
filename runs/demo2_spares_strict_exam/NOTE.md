# Spares: first exam on the stricter, newer factory (18/25)

**What this is.** The same brief and documents as `demo2_spares`, run on newer code with ambiguous cases and computed tool
cases. It contains the **first exam only**: there are no improvement rounds, because the free tier's daily token limit
would not allow them before the deadline. The full loop for this corpus is in `../demo2_spares`.

**Models.** Agent and generator `openai/gpt-oss-20b`, judge `qwen/qwen3.8-27b`. No substitutions and no outages. The code
is the commit "Reject test questions that refer to the generator's passages".

**The seven failures, read by hand.**
- Real agent failures (4): one ambiguous question answered for only one reading; one near-miss answered although the
  documents say nothing about hull coating; two price differences that are numerically right but computed without the
  calculator, which the agent's own rules forbid.
- Weaknesses of the exam or judge (3): one test required an amount range the question did not ask for; one required two
  whole sentences, so a correct paraphrase failed; one correct table lookup ("1") was rejected because its wording
  differed from the column name. The judge has since been fixed for that last case.

The score has not been adjusted.

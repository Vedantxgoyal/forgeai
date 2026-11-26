# Third brief: everything on a 3B model on a CPU laptop (15/20)

**Why it exists.** A brief and document set different from the two main demos, run entirely on `llama3.2:3b` through local
Ollama (generator, agent and judge), to check that the factory still works with a weak model.

**Stopped after one improvement round** to meet the deadline; the artifacts were assembled from the cached model calls of
the same run. Round 1 added a vague rule, lowered the development score from 73% to 60%, and was rolled back.

**What the weak model needed from the pipeline** (each visible in the artifacts):
- It asked no usable clarifying questions, so three were assembled from the document profile (`02_questions.json`).
- It could not produce enough verifiable test cases, so 8 of the 20 are fill-in-the-blank cases built from the documents
  without a model. These are easier, so the score flatters the agent on those.
- The `weather` tool is justified by the sentence in the brief that asks for it.

**The five failures, read by hand.** In most of them the agent's answer is correct for the question but shorter than the
test's list of facts (for example "40 km/h"), so they are largely weaknesses of tests written by the same small model.
The two-document question is a real miss. The score has not been adjusted.

**Limits.** Judge and agent are the same model (self-preference possible), several judge calls returned unusable output
(recorded as "LLM judge unavailable", deterministic verdict kept), some agent replies were invalid and scored as such, and
no test case exercises the weather tool.

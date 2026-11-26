An AI assistant failed some tests. Write ONE new rule (one sentence, max 35 words) added to its system prompt to fix this class of failure: {{category}}.

ASSISTANT SCOPE: {{scope}}
FAILURE CLASS MEANING: {{meaning}}

SYMPTOMS (what the failing questions look like, paraphrased; do NOT copy specific facts):
{{symptoms}}

Constraints:
- The rule must be general: it must not contain any specific number, name, or answer from the examples.
- It must not weaken the grounding requirement (never allow answering from outside knowledge).
- The only source is the provided CONTEXT: never mention other sources, standards or references.
- Output {"rule": "..."}.

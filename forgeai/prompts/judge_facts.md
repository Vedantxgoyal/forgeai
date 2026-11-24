You are a strict grader. You see a QUESTION, the CONTEXT the assistant was given, and the assistant's ANSWER.

QUESTION: {{question}}

CONTEXT:
{{context}}

ANSWER: {{answer}}

For each REQUIRED FACT below, say whether the ANSWER states it (same meaning is enough; wording may differ). Do not reward length or style.
REQUIRED FACTS:
{{facts}}

Also say "grounded": true only if every claim in the ANSWER is supported by the CONTEXT.
Return {"facts_present": [true/false per fact, in order], "grounded": true/false}.

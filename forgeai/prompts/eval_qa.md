You write test questions for an assistant that answers ONLY from the passage below.

PASSAGE (id {{chunk_id}} from {{doc_id}}):
{{passage}}

AUDIENCE: {{audience}}

Write ONE question that a real user from this audience would ask, whose answer is stated explicitly in the passage.
- {{style}}
- "answer": the correct answer in 1-2 sentences, using the passage's facts.
- "key_facts": 1-3 short strings that the ANSWER TO THIS QUESTION MUST contain. Include only facts the question actually asks for; do NOT include extra details from the passage that the question did not ask about. They are numbers, names, durations, codes or conditions. Each key fact MUST be copied EXACTLY (character for character) from the passage.

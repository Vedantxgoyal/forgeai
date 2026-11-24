Write structured requirements for the assistant described below.

BRIEF:
{{brief}}

DOCUMENT PROFILE:
{{profile}}

CLARIFYING Q&A:
{{qa}}

Fill in:
- agent_name: short snake_case name.
- purpose: one sentence.
- audience: who uses it.
- tone: e.g. "formal, concise".
- scope: what the assistant covers, one or two sentences.
- must_answer_topics: 3-8 concrete topics it must answer, phrased as noun phrases that appear in the documents' vocabulary. Include a topic ONLY if the brief or Q&A asks for it; do not invent topics just because the documents contain them.
- must_refuse_topics: topics it must decline (things outside scope, advice it must not give, topics for other audiences). Include everything the Q&A or brief says to refuse.

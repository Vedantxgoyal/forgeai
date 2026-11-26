# Earlier runs

Kept as evidence of what real runs broke. Do not read their scores as results.

| Folder | Why it was superseded |
|---|---|
| `demo1_hr_run1_before_judge_fixes` | The judge marked correct answers wrong (Unicode hyphens, over-specified test facts) |
| `demo1_hr_run2` | **Iteration 3 is invalid:** 11 of its 24 cases hit rate-limit outages, which the code then scored as the agent refusing |
| `demo2_spares_run1_exam_without_tool_cases` | Scored 100% on an exam that never needed a tool |
| `demo2_spares_run2_before_final_fixes` | A list marker was judged as an invented number; changes that improved nothing were kept |
| `demo3_port_run1_guard_blocked_weather` | The guard told the agent to refuse the weather questions its tool exists for |
| `demo3_port_run2_only_11_cases` | A small corpus produced fewer than the required 20 test cases |
| `demo3_port_local_run1_no_interview` | Local 3B run (13/20): the model asked no clarifying questions, accepted rules pointing at outside sources, and its judge overruled supported answers |

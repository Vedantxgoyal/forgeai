# Provenance of this run
Models: agent/generator openai/gpt-oss-20b, judge qwen/qwen3.8-27b (Groq free tier).
Produced before the later fixes for tool-call recovery, bare-number matching, list-marker numbers and the
stricter "a change must improve a score" rule. This corpus has no tables, so the tool changes do not affect it.
Under the stricter rule the kept/rolled-back decisions below are unchanged (the accepted iteration improved the score).

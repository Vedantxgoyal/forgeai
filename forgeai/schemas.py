"""Typed artifacts passed between factory stages. Every stage persists its artifact as JSON/YAML."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ----------------------------- intake / guard ----------------------------- #
class Question(BaseModel):
    question: str
    why: str = ""  # which document feature motivated it
    grounded_in: list[str] = Field(default_factory=list)  # doc terms/headings/columns it references


class QuestionSet(BaseModel):
    questions: list[Question]


class QA(BaseModel):
    question: str
    answer: str
    source: Literal["user", "auto-default"] = "user"


class Answers(BaseModel):
    answers: list[str]


class RequirementsDraft(BaseModel):
    agent_name: str
    purpose: str
    audience: str
    tone: str
    scope: str
    must_answer_topics: list[str] = Field(min_length=1)
    must_refuse_topics: list[str] = Field(default_factory=list)


class TopicCheck(BaseModel):
    topic: str
    status: Literal["supported", "partial", "unsupported"]
    lexical_coverage: float
    best_chunks: list[str] = Field(default_factory=list)
    llm_verdict: str = ""
    note: str = ""


class Requirements(RequirementsDraft):
    qa: list[QA] = Field(default_factory=list)
    groundability: list[TopicCheck] = Field(default_factory=list)
    ungrounded_topics: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    brief: str = ""


# ----------------------------- agent definition --------------------------- #
class Rule(BaseModel):
    id: str
    text: str
    added_in_iteration: int = 0
    reason: str = ""
    category: str = "base"


class RetrievalConfig(BaseModel):
    chunk_size: int = 220
    chunk_overlap: int = 40
    top_k: int = 5
    mode: Literal["dense", "bm25", "hybrid"] = "hybrid"
    rerank: bool = False
    query_rewrite: bool = False


class ToolChoice(BaseModel):
    name: str
    justification: str  # verbatim quote from the brief/requirements that makes the tool necessary


class AgentDef(BaseModel):
    name: str
    version: int = 1
    model: str = ""
    role_prompt: str
    rules: list[Rule] = Field(default_factory=list)
    refusal_phrase: str = "I can't answer that from the provided documents."
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    tools: list[ToolChoice] = Field(default_factory=list)
    dropped_tools: list[dict] = Field(default_factory=list)
    dropped_rules: list[dict] = Field(default_factory=list)
    output_contract: dict = Field(default_factory=lambda: {
        "answer": "string, grounded only in the context",
        "citations": "list of chunk ids used, e.g. ['hr_policy#3']",
        "refused": "true if the documents cannot answer",
    })

    def system_prompt(self) -> str:
        rules = "\n".join(f"{i}. {r.text}" for i, r in enumerate(self.rules, 1))
        return f"{self.role_prompt}\n\nRULES:\n{rules}\n\nIf you must refuse, say exactly: \"{self.refusal_phrase}\""


class AgentTurn(BaseModel):
    """What the running agent returns each step (small models: keep it flat)."""
    action: Literal["answer", "tool"] = "answer"
    answer: str = ""
    citations: list[str] = Field(default_factory=list)
    refused: bool = False
    tool: str = ""
    args: dict = Field(default_factory=dict)


class ToolPick(BaseModel):
    name: str
    justification: str


class ToolPicks(BaseModel):
    tools: list[ToolPick] = Field(default_factory=list)


class RoleDraft(BaseModel):
    role_prompt: str
    rules: list[str] = Field(default_factory=list)


# ----------------------------- evals / judging ---------------------------- #
CaseType = Literal["answerable", "multi_doc", "paraphrase", "out_of_scope", "near_miss", "tool"]


class EvalCase(BaseModel):
    id: str
    type: CaseType
    question: str
    expected_refusal: bool = False
    reference_answer: str = ""
    key_facts: list[str] = Field(default_factory=list)
    source_docs: list[str] = Field(default_factory=list)
    gold_chunks: list[str] = Field(default_factory=list)
    split: Literal["dev", "holdout"] = "dev"
    verified: bool = True


class RawQA(BaseModel):
    question: str
    answer: str
    key_facts: list[str] = Field(min_length=1)


class RawQuestions(BaseModel):
    questions: list[str]


class AgentResponse(BaseModel):
    answer: str
    citations: list[str] = Field(default_factory=list)
    refused: bool = False
    retrieved: list[str] = Field(default_factory=list)
    context_text: str = ""
    tool_calls: list[dict] = Field(default_factory=list)
    seconds: float = 0.0
    rewritten_query: str = ""
    error: str = ""


class JudgeVote(BaseModel):
    facts_present: list[bool] = Field(default_factory=list)
    grounded: bool = True


class CaseResult(BaseModel):
    case_id: str
    type: str
    split: str
    passed: bool
    refused: bool
    fact_coverage: float = 1.0
    grounded: bool = True
    citation_ok: bool = True
    retrieval_hit: bool = True
    failure: str = ""  # retrieval_miss | prompt_defect | hallucination | wrong_refusal
    judge_note: str = ""
    judge_unstable: bool = False
    llm_overrode: bool = False
    answer: str = ""
    question: str = ""

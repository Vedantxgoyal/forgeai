"""Generic agent runtime: loads ANY AgentDef + a document folder and answers questions.

Nothing here knows about a particular domain. Behaviour comes entirely from the
definition (prompt rules, retrieval config, tool list), which lets the optimizer
change one knob at a time and re-run.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import yaml

from forgeai.config import Settings, get_settings
from forgeai.ingest.chunker import ChunkParams, chunk_documents
from forgeai.ingest.loaders import LoadResult, load_folder
from forgeai.llm.client import LLMClient, LLMUnavailable
from forgeai.llm.structured import generate_structured
from forgeai.retrieval.embed import get_embedder
from forgeai.retrieval.index import HybridIndex, Reranker, SearchParams
from forgeai.schemas import AgentDef, AgentResponse, AgentTurn
from forgeai.textutil import looks_like_refusal
from forgeai.tools import get_tools
from forgeai.tools.base import ToolContext

log = logging.getLogger(__name__)
MAX_TOOL_STEPS = 3


def load_agent_def(path: str | Path) -> AgentDef:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    data = yaml.safe_load(text) if p.suffix in (".yaml", ".yml") else json.loads(text)
    return AgentDef.model_validate(data)


def save_agent_def(d: AgentDef, path: str | Path) -> None:
    Path(path).write_text(yaml.safe_dump(d.model_dump(), sort_keys=False, allow_unicode=True, width=100), encoding="utf-8")


def build_index(load: LoadResult, d: AgentDef, settings: Settings, embedder=None) -> HybridIndex:
    chunks = chunk_documents(load.documents, ChunkParams(d.retrieval.chunk_size, d.retrieval.chunk_overlap))
    emb = embedder or get_embedder(settings)
    return HybridIndex(chunks, emb, Reranker(settings.st_reranker))


class Agent:
    def __init__(self, d: AgentDef, load: LoadResult, client: LLMClient, settings: Settings | None = None,
                 index: HybridIndex | None = None):
        self.d, self.load, self.client = d, load, client
        self.settings = settings or get_settings()
        self.index = index or build_index(load, d, self.settings)
        self.tools = {t.name: t for t in get_tools([t.name for t in d.tools])}
        self.ctx = ToolContext(tables=load.tables)
        self.model = d.model or self.settings.effective_agent_model

    @classmethod
    def from_files(cls, definition: str | Path, docs: str | Path, client: LLMClient | None = None):
        s = get_settings()
        return cls(load_agent_def(definition), load_folder(docs), client or LLMClient(s), s)

    # ------------------------------------------------------------------ #
    def _retrieval_query(self, question: str, history: list[dict]) -> tuple[str, str]:
        if not self.d.retrieval.query_rewrite:
            return question, ""
        prior = "\n".join(f"{m['role']}: {m['content']}" for m in history[-4:])
        msgs = [
            {"role": "system", "content": "Rewrite the user's question as a short keyword-rich search query for a document search engine. "
             "Name the concept in the formal terms a policy or catalogue would use. Output the query only."},
            {"role": "user", "content": (f"Conversation:\n{prior}\n\n" if prior else "") + f"Question: {question}"},
        ]
        try:
            q = self.client.chat(msgs, model=self.model, max_tokens=60, stage="agent_rewrite").strip().strip('"')
            return (q if 3 <= len(q) <= 300 else question), q
        except Exception:  # noqa: BLE001
            return question, ""

    def _tool_block(self) -> str:
        if not self.tools:
            return 'No tools are available. Always set action="answer".'
        specs = json.dumps([t.spec() for t in self.tools.values()], ensure_ascii=False)
        if "csv_lookup" in self.tools:
            tables = "; ".join(f"{name}(columns: {', '.join(map(str, df.columns))})" for name, df in self.ctx.tables.items())
            specs += f" | Tables for csv_lookup: {tables}"
        return 'TOOLS (use at most one per step: action="tool", tool=<name>, args={...}; you then see the result):\n' + specs

    def ask(self, question: str, history: list[dict] | None = None) -> AgentResponse:
        t0 = time.perf_counter()
        history = history or []
        q_ret, rewritten = self._retrieval_query(question, history)
        p = self.d.retrieval
        hits = self.index.search(q_ret, SearchParams(top_k=p.top_k, mode=p.mode, rerank=p.rerank))
        ctx_text = "\n\n".join(f"[{h.chunk.chunk_id}] {h.chunk.text}" for h in hits)
        retrieved = [h.chunk.chunk_id for h in hits]
        contract = json.dumps(self.d.output_contract, ensure_ascii=False)
        sys_msg = (
            f"{self.d.system_prompt()}\n\n{self._tool_block()}\n\n"
            'Reply with ONE JSON object: {"action":"answer|tool","answer":str,"citations":[chunk ids],"refused":bool,'
            f'"tool":str,"args":object}}. Contract: {contract}'
        )
        msgs = [{"role": "system", "content": sys_msg}, *history[-6:],
                {"role": "user", "content": f"CONTEXT:\n{ctx_text or '(nothing retrieved)'}\n\nQUESTION: {question}"}]
        calls: list[dict] = []
        fallback = AgentTurn(action="answer", answer=self.d.refusal_phrase, refused=True)
        turn, err = fallback, ""
        try:
            for _ in range(MAX_TOOL_STEPS + 1):
                res = generate_structured(self.client, AgentTurn, msgs, model=self.model, stage="agent",
                                          max_tokens=700, fallback=fallback)
                turn = res.value
                if res.used_fallback:
                    err = "agent output invalid after retries"
                    break
                if turn.action == "tool" and turn.tool in self.tools and len(calls) < MAX_TOOL_STEPS:
                    r = self.tools[turn.tool].run(self.ctx, **(turn.args or {}))
                    text = r.to_text()
                    calls.append({"tool": turn.tool, "args": turn.args, "ok": r.ok, "result": text[:800]})
                    msgs = [*msgs, {"role": "assistant", "content": json.dumps(turn.model_dump())},
                            {"role": "user", "content": f'TOOL RESULT ({turn.tool}): {text}\nNow give the final answer (action="answer").'}]
                    ctx_text += f"\n\n[tool:{turn.tool}] {text}"
                    continue
                break
        except Exception as exc:  # noqa: BLE001 - a bad model reply must not crash the chat loop
            if isinstance(exc, LLMUnavailable) and re.search(r"RateLimit|Connection|Timeout|InternalServer", str(exc)):
                raise  # an outage is not agent behaviour: never let it be scored as a refusal
            err = f"{type(exc).__name__}: {exc}"[:200]
            turn = fallback
        if turn.action == "tool":
            turn = AgentTurn(action="answer", answer=self.d.refusal_phrase, refused=True)
        refused = turn.refused or looks_like_refusal(turn.answer, self.d.refusal_phrase)
        cites = [c.strip("[] ") for c in turn.citations]
        return AgentResponse(answer=turn.answer.strip(), citations=cites, refused=refused, retrieved=retrieved,
                             context_text=ctx_text, tool_calls=calls, seconds=time.perf_counter() - t0,
                             rewritten_query=rewritten, error=err)

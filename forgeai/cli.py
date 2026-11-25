"""ForgeAI command line.

Factory:
  forge run <docs> --brief "..."    build, examine, improve and report on an agent
  forge chat <agent.yaml> <docs>    run any generated agent
  forge regress <run> <new docs>    re-run the old exam after documents change
  forge compare <run> <agent.yaml>  factory agent vs a hand-written one
  forge ui                          web interface

Inspection:
  forge inspect <folder>            corpus profile + chunking stats
  forge search  <folder> "<query>"  hybrid retrieval with full trace
  forge tools                       registry capability cards
  forge ping                        check the LLM endpoint
"""

from __future__ import annotations

import json
import logging

import typer
from rich.console import Console
from rich.table import Table

from forgeai.config import get_settings

app = typer.Typer(add_completion=False, no_args_is_help=True, help="ForgeAI - the agent that builds agents.")
console = Console()


@app.callback()
def _main(verbose: bool = typer.Option(False, "--verbose", "-v")):
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


@app.command()
def inspect(folder: str, as_json: bool = typer.Option(False, "--json")):
    """Profile a document folder: files, sections, columns, warnings, chunk stats."""
    from forgeai.ingest.chunker import chunk_documents, suggest_params
    from forgeai.ingest.loaders import load_folder
    from forgeai.ingest.profiler import profile_corpus

    res = load_folder(folder)
    prof = profile_corpus(res)
    params = suggest_params(res.documents)
    chunks = chunk_documents(res.documents, params)
    if as_json:
        console.print_json(
            json.dumps({"profile": prof.to_dict(), "chunk_params": vars(params), "n_chunks": len(chunks)}, default=str)
        )
        return
    t = Table(title=f"Corpus: {folder}")
    for col in ("doc_id", "kind", "words", "pages/rows", "sections/columns", "warnings"):
        t.add_column(col)
    for d in prof.docs:
        t.add_row(
            d.doc_id,
            d.kind,
            str(d.n_words),
            str(d.n_pages or d.n_rows or ""),
            str(len(d.columns) if d.columns else len(d.headings)),
            "; ".join(d.warnings)[:60],
        )
    console.print(t)
    for f, why in prof.skipped:
        console.print(f"[yellow]skipped[/] {f}: {why}")
    console.print(f"Suggested chunking: size={params.chunk_size} words, overlap={params.chunk_overlap} -> {len(chunks)} chunks")


@app.command()
def search(
    folder: str,
    query: str,
    top_k: int = 5,
    mode: str = typer.Option("hybrid", help="dense | bm25 | hybrid"),
    rerank: bool = False,
):
    """Run hybrid retrieval over a folder and print the retrieval trace."""
    from forgeai.ingest.chunker import chunk_documents, suggest_params
    from forgeai.ingest.loaders import load_folder
    from forgeai.retrieval.embed import get_embedder
    from forgeai.retrieval.index import HybridIndex, Reranker, SearchParams

    s = get_settings()
    res = load_folder(folder)
    chunks = chunk_documents(res.documents, suggest_params(res.documents))
    idx = HybridIndex(chunks, get_embedder(s), Reranker(s.st_reranker) if rerank else None)
    console.print(f"[dim]embedder={idx.embedder.name} chunks={len(idx)}[/]")
    for h in idx.search(query, SearchParams(top_k=top_k, mode=mode, rerank=rerank)):
        tr = h.trace()
        console.print(
            f"[bold]{tr['chunk_id']}[/] score={tr['score']} dense#{tr['dense_rank']} bm25#{tr['bm25_rank']}"
            + (f" rerank={tr['rerank_score']}" if tr["rerank_score"] is not None else "")
        )
        console.print("   " + h.chunk.body[:220].replace("\n", " "))


@app.command()
def tools():
    """Show the tool registry's capability cards."""
    from forgeai.tools import registry_cards

    console.print(registry_cards())


@app.command()
def ping():
    """Check the configured LLM endpoint and models."""
    from forgeai.llm.client import LLMClient

    s = get_settings()
    client = LLMClient(s, use_cache=False)
    for label, model in (("generator", s.gen_model), ("judge", s.judge_model), ("agent", s.effective_agent_model)):
        try:
            out = client.chat(
                [{"role": "user", "content": "Reply with the single word: ok"}], model=model, max_tokens=5, stage="ping"
            )
            console.print(f"[green]OK[/] {label:9} {model}: {out.strip()[:30]!r}")
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]FAIL[/] {label:9} {model}: {exc}")


@app.command()
def run(
    docs: str = typer.Argument(..., help="folder of documents"),
    brief: str = typer.Option(..., "--brief", "-b", help="one-paragraph brief (or @file.txt)"),
    out: str = typer.Option("runs/run", "--out", "-o"),
    interactive: bool = typer.Option(False, "--interactive", "-i", help="answer the clarifying questions yourself"),
    approve: bool = typer.Option(False, "--approve", help="pause for human approval of the requirements"),
    cases: int = typer.Option(24, "--cases"),
    iters: int = typer.Option(3, "--iters"),
    workers: int = typer.Option(4, "--workers"),
    tournament: bool = typer.Option(False, "--tournament", help="let candidate prompts compete on dev cases first"),
    token_budget: int = typer.Option(0, "--token-budget", help="stop improving before this many tokens (0 = none)"),
    max_minutes: float = typer.Option(0, "--max-minutes", help="stop improving before this much time (0 = none)"),
):
    """Build, test and tune an agent from a brief + documents. Writes every artifact to --out."""
    from pathlib import Path

    from forgeai.factory.pipeline import run_factory

    if brief.startswith("@"):
        brief = Path(brief[1:]).read_text(encoding="utf-8").strip()

    def ask(q: str) -> str:
        return console.input(f"[bold cyan]? {q}[/]\n> ")

    def approver(req):
        """Human checkpoint: edit the YAML in any editor, then approve or reject."""
        import yaml

        from forgeai.schemas import Requirements

        path = Path(out) / "requirements.review.yaml"
        editable = req.model_dump(exclude={"qa", "groundability", "brief", "assumptions"})
        path.write_text(yaml.safe_dump(editable, sort_keys=False, allow_unicode=True), encoding="utf-8")
        for c in req.groundability:
            console.print(f"  {c.status:12} {c.topic}")
        console.print(path.read_text(encoding="utf-8"))
        while True:
            answer = console.input(f"Edit [bold]{path}[/] if needed, save, then type a (approve) or r (reject): ").strip().lower()
            if answer == "r":
                return False
            if answer != "a":
                continue
            try:
                changed = yaml.safe_load(path.read_text(encoding="utf-8"))
                return Requirements.model_validate({**req.model_dump(), **changed})
            except Exception as exc:  # noqa: BLE001 - let the reviewer fix the file
                console.print(f"[red]The file is not valid:[/] {str(exc)[:300]}")

    run_factory(
        brief,
        docs,
        out,
        ask=ask if interactive else None,
        approve=approver if approve else None,
        n_cases=cases,
        max_iters=iters,
        workers=workers,
        tournament=tournament,
        token_budget=token_budget,
        max_seconds=max_minutes * 60,
        on_event=lambda m: console.print(f"[green]{m}[/]"),
    )


@app.command()
def regress(
    old_run: str = typer.Argument(..., help="a finished run folder"),
    new_docs: str = typer.Argument(..., help="the changed document folder"),
    out: str = typer.Option("runs/regression", "--out", "-o"),
    workers: int = typer.Option(4, "--workers"),
):
    """Documents changed: regenerate the agent, re-run the OLD exam and report what broke."""
    from forgeai.factory.regression import run_regression

    summary = run_regression(old_run, new_docs, out, workers=workers, on_event=lambda m: console.print(f"[green]{m}[/]"))
    console.print(summary["counts"])


@app.command()
def compare(
    run_dir: str = typer.Argument(..., help="a finished run folder (its exam is reused)"),
    definition: str = typer.Argument(..., help="a hand-written agent definition (.yaml)"),
    workers: int = typer.Option(4, "--workers"),
):
    """Factory vs hand-written agent on the same exam. Writes comparison.md into the run folder."""
    from forgeai.factory.baseline import compare_agents

    console.print(compare_agents(run_dir, definition, workers=workers))


@app.command()
def chat(
    definition: str = typer.Argument(..., help="agent definition (.yaml/.json) produced by `forge run`"),
    docs: str = typer.Argument(..., help="document folder the agent answers from"),
    trace: bool = typer.Option(False, "--trace", help="show retrieved chunks, tool calls"),
):
    """Chat with ANY generated agent definition."""
    from forgeai.agent.runtime import Agent

    agent = Agent.from_files(definition, docs)
    console.print(
        f"[bold]{agent.d.name}[/] v{agent.d.version} | tools: {[t.name for t in agent.d.tools] or 'none'} | {len(agent.index)} chunks. Ctrl+C to quit."
    )
    history: list[dict] = []
    while True:
        try:
            q = console.input("[bold cyan]you>[/] ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if not q:
            continue
        try:
            r = agent.ask(q, history)
        except Exception as exc:  # noqa: BLE001 - keep the session alive during an outage
            console.print(f"[red]model unavailable:[/] {str(exc)[:200]}")
            continue
        console.print(f"[bold green]agent>[/] {r.answer}")
        if r.citations:
            console.print(f"[dim]sources: {', '.join(r.citations)}[/]")
        if trace:
            console.print(f"[dim]retrieved: {r.retrieved} | tools: {r.tool_calls} | {r.seconds:.1f}s[/]")
        history += [{"role": "user", "content": q}, {"role": "assistant", "content": r.answer}]


@app.command()
def ui(port: int = 8600, host: str = typer.Option("127.0.0.1", help="use 0.0.0.0 only with FORGE_PUBLIC=1")):
    """Serve the web frontend (build it once: cd web, npm install, npm run build)."""
    import uvicorn

    console.print(f"ForgeAI UI on http://{host}:{port}")
    uvicorn.run("forgeai.server:app", host=host, port=port, log_level="warning")


if __name__ == "__main__":
    app()

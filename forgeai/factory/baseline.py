"""Factory vs human: score a hand-written agent definition on the exam a factory run produced.

Both agents sit the same exam with the same judge. Note the bias this cannot remove: the factory's optimizer
saw the development cases and the human did not, so the hold-out column is the fair comparison.
"""

from __future__ import annotations

import json
from pathlib import Path

from forgeai.agent.runtime import Agent, load_agent_def
from forgeai.config import get_settings
from forgeai.factory.optimizer import run_exam, score
from forgeai.ingest.loaders import load_folder
from forgeai.llm.client import LLMClient
from forgeai.schemas import CaseResult, EvalCase


def compare_agents(run_dir: str | Path, definition: str | Path, *, workers: int = 4, client: LLMClient | None = None) -> str:
    run = Path(run_dir)
    s = get_settings()
    client = client or LLMClient(s)
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    cases = [EvalCase.model_validate(c) for c in json.loads((run / "04_evals.json").read_text(encoding="utf-8"))["cases"]]
    iterations = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(run.glob("05_iteration_*.json"))]
    factory = [CaseResult.model_validate(r) for r in [i for i in iterations if i["accepted"]][-1]["results"]]
    hand_def = load_agent_def(definition)
    hand = run_exam(Agent(hand_def, load_folder(manifest["docs"]), client, s), cases, client, s.judge_model, workers)

    def row(name: str, rs: list[CaseResult]) -> str:
        return f"| {name} | {sum(r.passed for r in rs)}/{len(rs)} | {score(rs, 'dev'):.0%} | {score(rs, 'holdout'):.0%} |"

    wins = [(c, f, h) for c, f, h in zip(cases, factory, hand) if f.passed != h.passed]
    L = [
        f"# Factory vs hand-written agent: {run.name}",
        "",
        f"Hand-written definition: `{definition}`",
        "",
        "| Agent | Passed | Dev | Hold-out |",
        "|---|---|---|---|",
        row("factory", factory),
        row("hand-written", hand),
        "",
        "The factory saw the dev cases while optimizing; compare the hold-out column for a fair view.",
        "",
        "## Where they differ",
        "",
    ]
    L += [
        f'- **{"factory" if f.passed else "hand-written"} wins** `{c.id}` ({c.type}, {c.split}): "{c.question}"  \n'
        f'  loser said: "{(h if f.passed else f).answer[:160]}" ({(h if f.passed else f).failure})'
        for c, f, h in wins
    ] or ["- no differences"]
    (run / "comparison.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    return "\n".join(L[:9])

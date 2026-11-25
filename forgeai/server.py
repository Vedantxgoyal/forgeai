"""Web API behind the Vite frontend:  forge ui

Thin by design: it reads the artifacts a run wrote, chats through the same ``Agent`` the CLI uses, and
starts the same ``run_factory`` pipeline. It binds to localhost; it has no authentication, so do not
expose it publicly as-is.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
import uuid
from pathlib import Path

import yaml
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from forgeai.agent.runtime import Agent
from forgeai.config import get_settings
from forgeai.ingest.loaders import load_folder
from forgeai.llm.client import LLMClient

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
DIST = ROOT / "web" / "dist"
_NAME = re.compile(r"^[A-Za-z0-9_-]{1,60}$")
os.chdir(ROOT)  # .env, the LLM cache and relative document paths resolve against the project folder
_ALLOWED = {".pdf", ".docx", ".csv", ".tsv", ".xlsx", ".md", ".txt", ".html", ".htm"}
MAX_UPLOAD = 15 * 1024 * 1024

app = FastAPI(title="ForgeAI")
_agents: dict[str, tuple[float, Agent]] = {}
_jobs: dict[str, dict] = {}
_build_lock = threading.Lock()


def _run_dir(name: str) -> Path:
    if not _NAME.match(name) or not (RUNS / name / "agent.final.yaml").exists():
        raise HTTPException(404, "run not found")
    return RUNS / name


def _json(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _docs_dir(run: Path) -> Path:
    saved = run / "docs_path.txt"
    docs = Path(saved.read_text(encoding="utf-8").strip() if saved.exists() else _json(run / "manifest.json")["docs"])
    return docs if docs.is_absolute() else ROOT / docs


@app.get("/api/runs")
def list_runs():
    out = []
    for p in sorted(RUNS.glob("*/agent.final.yaml")):
        run = p.parent
        iters = [_json(f) for f in sorted(run.glob("05_iteration_*.json"))]
        accepted = [i for i in iters if i["accepted"]]
        if not accepted:
            continue
        last, m = accepted[-1], _json(run / "manifest.json")
        out.append({"name": run.name, "brief": m["brief"], "tools": m["tools"], "passed": last["n_pass"], "total": last["n_total"]})
    return out


@app.get("/api/runs/{name}")
def get_run(name: str):
    run = _run_dir(name)
    return {
        "name": name,
        "manifest": _json(run / "manifest.json"),
        "profile": _json(run / "01_corpus_profile.json"),
        "questions": _json(run / "02_questions.json"),
        "requirements": _json(run / "02_requirements.json"),
        "agent": yaml.safe_load(_text(run / "agent.final.yaml")),
        "agent_yaml": _text(run / "agent.final.yaml"),
        "evals": _json(run / "04_evals.json"),
        "iterations": [_json(f) for f in sorted(run.glob("05_iteration_*.json"))],
        "report": _text(run / "report.md"),
        "note": _text(run / "NOTE.md"),
    }


class ChatIn(BaseModel):
    question: str
    history: list[dict] = []


@app.post("/api/runs/{name}/chat")
def chat(name: str, body: ChatIn):
    run = _run_dir(name)
    question = body.question.strip()
    if not 0 < len(question) <= 2000:
        raise HTTPException(400, "question must be 1-2000 characters")
    definition = run / "agent.final.yaml"
    stamp = definition.stat().st_mtime
    try:
        if name not in _agents or _agents[name][0] != stamp:
            _agents[name] = (stamp, Agent.from_files(definition, _docs_dir(run)))
        history = [{"role": m["role"], "content": str(m["content"])[:2000]} for m in body.history[-6:]
                   if m.get("role") in ("user", "assistant")]
        r = _agents[name][1].ask(question, history)
    except Exception as exc:  # noqa: BLE001 - report the reason (usually a model quota) to the page
        raise HTTPException(503, f"{type(exc).__name__}: {str(exc)[:300]}") from exc
    return r.model_dump(exclude={"context_text"})


def _build(job: dict, brief: str, docs: Path, out: Path, cases: int) -> None:
    from forgeai.factory.pipeline import run_factory

    def event(message: str) -> None:
        job["events"].append(message.rstrip())
        stage = re.match(r"\[(\d)/7\]", message)
        if stage:
            job["stage"] = int(stage.group(1))

    with _build_lock:  # one build at a time: free-tier rate limits make parallel builds pointless
        job["status"] = "running"
        try:
            s = get_settings()
            run_factory(brief, docs, out, settings=s, client=LLMClient(s), n_cases=cases, workers=2, on_event=event)
            (out / "docs_path.txt").write_text(str(docs), encoding="utf-8")
            job["status"] = "done"
        except BaseException as exc:  # noqa: BLE001 - SystemExit included: show the reason on the page
            job["status"], job["error"] = "failed", f"{type(exc).__name__}: {str(exc)[:400]}"


@app.post("/api/build")
async def build(brief: str = Form(...), name: str = Form(...), cases: int = Form(24), files: list[UploadFile] = File(...)):
    if not _NAME.match(name):
        raise HTTPException(400, "name: letters, digits, _ and - only")
    if (RUNS / name).exists():
        raise HTTPException(409, "a run with this name already exists; choose another")
    if len(brief.strip()) < 20:
        raise HTTPException(400, "brief is too short")
    docs = Path(tempfile.mkdtemp(prefix="forge_docs_"))
    for f in files[:30]:
        fname = Path(f.filename or "").name
        if Path(fname).suffix.lower() not in _ALLOWED:
            raise HTTPException(400, f"unsupported file type: {fname}")
        data = await f.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, f"{fname} is larger than 15 MB")
        (docs / fname).write_bytes(data)
    job_id = uuid.uuid4().hex[:12]
    job = _jobs[job_id] = {"id": job_id, "name": name, "status": "queued", "stage": 0, "events": [], "error": "", "started": time.time()}
    threading.Thread(target=_build, args=(job, brief.strip(), docs, RUNS / name, min(max(cases, 20), 30)), daemon=True).start()
    return job


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(404, "job not found")
    return _jobs[job_id]


if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="web")
else:
    @app.get("/", response_class=HTMLResponse)
    def _missing():
        return "<p>Frontend not built. Run: <code>cd web && npm install && npm run build</code></p>"

"""Web API behind the Vite frontend:  forge ui

Thin by design: it reads the artifacts a run wrote, chats through the same ``Agent`` the CLI uses, and
starts the same ``run_factory`` pipeline.

Hosting safeguards (environment variables):
  FORGE_PUBLIC=1          the server is reachable by strangers: building is OFF unless an access code is set
  FORGE_ACCESS_CODE=...   required (header ``X-Access-Code``) to build an agent or approve requirements
  FORGE_CHAT_PER_MINUTE   chat requests per client per minute (default 10)
  FORGE_CHAT_PER_DAY      chat requests per day across all clients (default 300), to protect the model quota
"""

from __future__ import annotations

import hmac
import json
import os
import re
import tempfile
import threading
import time
import uuid
from pathlib import Path

import yaml
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from forgeai.agent.runtime import Agent
from forgeai.config import get_settings
from forgeai.llm.client import LLMClient

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
DIST = ROOT / "web" / "dist"
_NAME = re.compile(r"^[A-Za-z0-9_-]{1,60}$")
os.chdir(ROOT)  # .env, the LLM cache and relative document paths resolve against the project folder
_ALLOWED = {".pdf", ".docx", ".csv", ".tsv", ".xlsx", ".md", ".txt", ".html", ".htm"}
MAX_UPLOAD = 15 * 1024 * 1024
MAX_TOTAL_UPLOAD = 40 * 1024 * 1024
MAX_PENDING_JOBS = 3
REVIEW_TIMEOUT_S = 30 * 60
PUBLIC = os.getenv("FORGE_PUBLIC", "") in ("1", "true", "yes")
ACCESS_CODE = os.getenv("FORGE_ACCESS_CODE", "")
CHAT_PER_MINUTE = int(os.getenv("FORGE_CHAT_PER_MINUTE", "10"))
CHAT_PER_DAY = int(os.getenv("FORGE_CHAT_PER_DAY", "300"))

app = FastAPI(title="ForgeAI")
_agents: dict[str, tuple[float, Agent]] = {}
_jobs: dict[str, dict] = {}
_reviews: dict[str, dict] = {}
_build_lock = threading.Lock()
_chat_log: list[tuple[float, str]] = []
_chat_lock = threading.Lock()


def build_enabled() -> bool:
    return bool(ACCESS_CODE) or not PUBLIC


def require_builder(x_access_code: str = Header(default="")) -> None:
    if not build_enabled():
        raise HTTPException(403, "building is disabled on this public demo")
    if ACCESS_CODE and not hmac.compare_digest(x_access_code.encode(), ACCESS_CODE.encode()):
        raise HTTPException(401, "wrong or missing access code")


def limit_chat(request: Request) -> None:
    # behind a hosting proxy the client address arrives in X-Forwarded-For (last hop is the proxy's own)
    forwarded = request.headers.get("x-forwarded-for", "")
    who = forwarded.split(",")[0].strip() if PUBLIC and forwarded else (request.client.host if request.client else "?")
    now = time.time()
    with _chat_lock:
        _chat_log[:] = [x for x in _chat_log if now - x[0] < 86400]
        if len(_chat_log) >= CHAT_PER_DAY:
            raise HTTPException(429, "the demo's daily chat limit is used up; please try again tomorrow")
        if sum(1 for t, w in _chat_log if w == who and now - t < 60) >= CHAT_PER_MINUTE:
            raise HTTPException(429, "too many messages; wait a minute")
        _chat_log.append((now, who))


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


@app.get("/api/config")
def config():
    return {"build_enabled": build_enabled(), "needs_code": bool(ACCESS_CODE)}


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
        out.append(
            {"name": run.name, "brief": m["brief"], "tools": m["tools"], "passed": last["n_pass"], "total": last["n_total"]}
        )
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


@app.post("/api/runs/{name}/chat", dependencies=[Depends(limit_chat)])
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
        history = [
            {"role": m["role"], "content": str(m["content"])[:2000]}
            for m in body.history[-6:]
            if m.get("role") in ("user", "assistant")
        ]
        r = _agents[name][1].ask(question, history)
    except Exception as exc:  # noqa: BLE001 - report the reason (usually a model quota) to the page
        raise HTTPException(503, f"{type(exc).__name__}: {str(exc)[:300]}") from exc
    return r.model_dump(exclude={"context_text"})


def _reviewer(job: dict):
    """Human checkpoint for the web: pause the build until the requirements are approved, edited or rejected."""
    from forgeai.schemas import Requirements

    def review(req: Requirements):
        gate = _reviews[job["id"]] = {"event": threading.Event(), "decision": None, "req": req}
        job["requirements"] = req.model_dump(exclude={"qa", "groundability", "brief", "assumptions"})
        job["groundability"] = [c.model_dump() for c in req.groundability]
        job["status"] = "awaiting_approval"
        gate["event"].wait(REVIEW_TIMEOUT_S)
        job["status"] = "running"
        _reviews.pop(job["id"], None)
        return gate["decision"]

    return review


def _build(job: dict, brief: str, docs: Path, out: Path, cases: int, review: bool, tournament: bool) -> None:
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
            run_factory(
                brief,
                docs,
                out,
                settings=s,
                client=LLMClient(s),
                n_cases=cases,
                workers=2,
                on_event=event,
                approve=_reviewer(job) if review else None,
                tournament=tournament,
            )
            (out / "docs_path.txt").write_text(str(docs), encoding="utf-8")
            job["status"] = "done"
        except BaseException as exc:  # noqa: BLE001 - SystemExit included: show the reason on the page
            job["status"], job["error"] = "failed", f"{type(exc).__name__}: {str(exc)[:400]}"


@app.post("/api/build", dependencies=[Depends(require_builder)])
async def build(
    brief: str = Form(...),
    name: str = Form(...),
    cases: int = Form(24),
    review: bool = Form(False),
    tournament: bool = Form(False),
    files: list[UploadFile] = File(...),
):
    if not _NAME.match(name):
        raise HTTPException(400, "name: letters, digits, _ and - only")
    if (RUNS / name).exists() or any(j["name"] == name and j["status"] != "failed" for j in _jobs.values()):
        raise HTTPException(409, "a run with this name already exists; choose another")
    if not 20 <= len(brief.strip()) <= 3000:
        raise HTTPException(400, "brief must be 20-3000 characters")
    if sum(j["status"] not in ("done", "failed") for j in _jobs.values()) >= MAX_PENDING_JOBS:
        raise HTTPException(429, "too many builds are waiting; try later")
    docs = Path(tempfile.mkdtemp(prefix="forge_docs_"))
    total = 0
    for f in files[:30]:
        fname = Path(f.filename or "").name
        if Path(fname).suffix.lower() not in _ALLOWED:
            raise HTTPException(400, f"unsupported file type: {fname}")
        data = await f.read(MAX_UPLOAD + 1)
        total += len(data)
        if len(data) > MAX_UPLOAD or total > MAX_TOTAL_UPLOAD:
            raise HTTPException(413, "upload too large (15 MB per file, 40 MB in total)")
        (docs / fname).write_bytes(data)
    job_id = uuid.uuid4().hex
    job = _jobs[job_id] = {
        "id": job_id,
        "name": name,
        "status": "queued",
        "stage": 0,
        "events": [],
        "error": "",
        "started": time.time(),
    }
    args = (job, brief.strip(), docs, RUNS / name, min(max(cases, 20), 30), review, tournament)
    threading.Thread(target=_build, args=args, daemon=True).start()
    return job


class ApprovalIn(BaseModel):
    approved: bool
    requirements: dict | None = None


@app.post("/api/jobs/{job_id}/approve", dependencies=[Depends(require_builder)])
def approve(job_id: str, body: ApprovalIn):
    from forgeai.schemas import Requirements

    gate = _reviews.get(job_id)
    if gate is None:
        raise HTTPException(409, "this build is not waiting for approval")
    if not body.approved:
        gate["decision"] = False
    elif body.requirements is None:
        gate["decision"] = True
    else:
        editable = {k: v for k, v in body.requirements.items() if k not in ("qa", "groundability", "brief", "assumptions")}
        try:
            gate["decision"] = Requirements.model_validate({**gate["req"].model_dump(), **editable})
        except ValueError as exc:
            raise HTTPException(400, f"requirements are not valid: {str(exc)[:300]}") from exc
    gate["event"].set()
    return {"ok": True}


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

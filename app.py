"""ForgeAI web UI:  streamlit run app.py

Browse any run (scorecard, requirements, exam, report), chat with its agent, or build a new one.
It only reads run artifacts and calls the same functions as the CLI.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)  # .env and the cache are resolved relative to the project folder

# Streamlit Cloud secrets -> environment, so the same Settings class works locally and hosted.
try:
    for k, v in st.secrets.items():
        if k.startswith("FORGE_"):
            os.environ.setdefault(k, str(v))
except Exception:  # noqa: BLE001 - no secrets file locally
    pass

from forgeai.agent.runtime import Agent  # noqa: E402

RUNS = ROOT / "runs"

st.set_page_config(page_title="ForgeAI", page_icon="⚒️", layout="wide")
st.title("⚒️ ForgeAI — the agent that builds agents")


def read_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def finished_runs() -> list[Path]:
    return sorted(p.parent for p in RUNS.glob("*/agent.final.yaml"))


@st.cache_resource(show_spinner="Indexing documents…")
def load_agent(definition: str, docs: str, _stamp: float) -> Agent:
    return Agent.from_files(definition, docs)


runs = finished_runs()
mode = st.sidebar.radio("Mode", ["Inspect & chat", "Build a new agent"])

if mode == "Build a new agent":
    brief = st.text_area("One-paragraph brief", height=100)
    files = st.file_uploader("Documents (PDF, DOCX, CSV, XLSX, MD, TXT, HTML)", accept_multiple_files=True)
    name = st.text_input("Run name", "my_agent")
    cases = st.slider("Test cases", 20, 30, 24)
    st.caption("Clarifying questions are answered with conservative defaults here. Use `forge run -i` to answer them yourself.")
    if st.button("Forge it", type="primary", disabled=not (brief and files)):
        from forgeai.factory.pipeline import run_factory

        safe = "".join(c for c in name if c.isalnum() or c in "-_") or "my_agent"
        docs = Path(tempfile.mkdtemp(prefix="forge_docs_"))
        for f in files:
            (docs / Path(f.name).name).write_bytes(f.getvalue())
        out = RUNS / safe
        with st.status("Running the factory (several minutes)…", expanded=True) as status:
            try:
                run_factory(brief, docs, out, n_cases=cases, workers=2, on_event=status.write)
                (out / "docs_path.txt").write_text(str(docs), encoding="utf-8")
                status.update(label="Done. Switch to 'Inspect & chat'.", state="complete")
            except BaseException as exc:  # noqa: BLE001 - show the reason instead of a stack trace
                status.update(label=f"Failed: {type(exc).__name__}: {exc}", state="error")
    st.stop()

if not runs:
    st.info("No finished runs yet. Build one, or run `forge run` from the terminal.")
    st.stop()

run = st.sidebar.selectbox("Run", runs, format_func=lambda p: p.name)
manifest = read_json(run / "manifest.json")
saved = run / "docs_path.txt"
default_docs = saved.read_text(encoding="utf-8") if saved.exists() else str(ROOT / manifest["docs"])
docs_dir = st.sidebar.text_input("Document folder", default_docs, key=f"docs_{run.name}")
st.sidebar.caption("Brief: " + manifest["brief"])
st.sidebar.caption("Tools: " + (", ".join(manifest["tools"]) or "none"))

tab_score, tab_chat, tab_req, tab_exam, tab_agent = st.tabs(["Scorecard", "Chat", "Requirements", "Exam", "Agent & report"])

iterations = [read_json(p) for p in sorted(run.glob("05_iteration_*.json"))]
final = [i for i in iterations if i["accepted"]][-1]

with tab_score:
    a, b, c = st.columns(3)
    a.metric("Final score", f"{final['n_pass']}/{final['n_total']}",
             f"{(final['overall_score'] - iterations[0]['overall_score']) * 100:+.0f} pts vs baseline")
    b.metric("Dev split", f"{final['dev_score']:.0%}")
    c.metric("Hold-out split", f"{final['holdout_score']:.0%}")
    st.table([{"iteration": i["iteration"], "overall": f"{i['overall_score']:.0%}", "dev": f"{i['dev_score']:.0%}",
               "hold-out": f"{i['holdout_score']:.0%}", "outcome": i["note"]} for i in iterations])
    for i in iterations[1:]:
        for ch in i["changes"]:
            st.markdown(f"**Iteration {i['iteration']} · {ch['category']}** ({'kept' if i['accepted'] else 'rolled back'}): {ch['detail']}")

with tab_req:
    req = read_json(run / "02_requirements.json")
    st.subheader("Groundability guard")
    st.table([{"topic": g["topic"], "status": g["status"], "coverage": g["lexical_coverage"], "note": g["note"]} for g in req["groundability"]])
    st.subheader("Clarifying questions and answers")
    for x in req["qa"]:
        st.markdown(f"**{x['question']}**  \n{x['answer']} _({x['source']})_")
    st.subheader("Requirements")
    st.json({k: v for k, v in req.items() if k not in ("qa", "groundability")}, expanded=False)

with tab_exam:
    results = {r["case_id"]: r for r in final["results"]}
    only_failed = st.checkbox("Only failures")
    for case in read_json(run / "04_evals.json")["cases"]:
        r = results.get(case["id"])
        if not r or (only_failed and r["passed"]):
            continue
        with st.expander(f"{'✅' if r['passed'] else '❌'} [{case['type']} · {case['split']}] {case['question']}"):
            st.write("**Agent:**", r["answer"])
            st.write("**Expected:**", "refusal" if case["expected_refusal"] else case["key_facts"])
            if r["failure"] or r["judge_note"]:
                st.write("**Judge:**", r["failure"], r["judge_note"])

with tab_agent:
    st.code((run / "agent.final.yaml").read_text(encoding="utf-8"), language="yaml")
    st.markdown((run / "report.md").read_text(encoding="utf-8"))

# Rendered last: loading the search model is slow and must not delay the other tabs.
with tab_chat:
    if not Path(docs_dir).is_dir():
        st.warning("Document folder not found.")
    else:
        definition = run / "agent.final.yaml"
        agent = load_agent(str(definition), docs_dir, definition.stat().st_mtime)
        key = f"chat_{run.name}"
        history = st.session_state.setdefault(key, [])
        for m in history:
            st.chat_message(m["role"]).write(m["content"])
        if q := st.chat_input("Ask the agent"):
            st.chat_message("user").write(q)
            with st.spinner("Thinking…"):
                try:
                    r = agent.ask(q, [{"role": m["role"], "content": m["content"]} for m in history])
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Model unavailable: {str(exc)[:200]}")
                    st.stop()
            with st.chat_message("assistant"):
                st.write(r.answer)
                st.caption(("Refused · " if r.refused else "") + "sources: " + (", ".join(r.citations) or "none"))
                with st.expander("Trace: retrieval and tool calls"):
                    st.json({"retrieved": r.retrieved, "tool_calls": r.tool_calls, "seconds": round(r.seconds, 1), "error": r.error})
            history += [{"role": "user", "content": q}, {"role": "assistant", "content": r.answer}]

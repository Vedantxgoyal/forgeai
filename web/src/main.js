import './style.css';
import { createForge } from './scene.js';
import { STAGES, esc, finalIteration, pct, stageStates, wilson } from './views.js';

const $ = (s) => document.querySelector(s);
const state = { run: null, stage: 2, history: [], job: null };

async function api(path, options) {
  const res = await fetch(path, options);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${res.status})`);
  return body;
}

const forge = createForge($('#stage3d'), $('#labels'), STAGES, select);
STAGES.forEach((s, i) => {
  const b = document.createElement('button');
  b.innerHTML = `<b>${i + 1}</b> ${s.title}`;
  b.addEventListener('click', () => select(i));
  $('#rail').appendChild(b);
});

const railChat = document.createElement('button');
railChat.className = 'rail-chat';
railChat.textContent = 'Chat';
railChat.addEventListener('click', () => $('#open-chat').click());
$('#rail').appendChild(railChat);

function select(i) {
  state.stage = i;
  forge.select(i);
  [...$('#rail').children].slice(0, STAGES.length).forEach((b, n) => b.classList.toggle('on', n === i));
  if (state.run) $('#panel').innerHTML = STAGES[i].view(state.run);
}

$('#panel').addEventListener('click', (e) => {
  const f = e.target.closest('#filters button');
  if (!f) return;
  [...f.parentElement.children].forEach((b) => b.classList.toggle('on', b === f));
  const want = f.dataset.f;
  document.querySelectorAll('.case').forEach((c) => {
    c.hidden = !(want === 'all' || (want === 'fail' ? c.dataset.pass === 'false' : c.dataset.type === want));
  });
});

async function loadRun(name) {
  const run = await api(`/api/runs/${encodeURIComponent(name)}`);
  state.run = run;
  state.history = [];
  const last = finalIteration(run), first = run.iterations[0];
  const [lo, hi] = wilson(last.n_pass, last.n_total);
  const delta = Math.round((last.overall_score - first.overall_score) * 100);
  $('#verdict').innerHTML = `
    <p class="eyebrow">Exam result</p>
    <p class="score">${last.n_pass}<span>/${last.n_total}</span></p>
    <p>95% interval <b>${pct(lo)} to ${pct(hi)}</b></p>
    <dl><dt>Baseline to final</dt><dd>${delta >= 0 ? '+' : ''}${delta} pts</dd>
    <dt>Dev / hold-out</dt><dd>${pct(last.dev_score)} / ${pct(last.holdout_score)}</dd>
    <dt>Tools</dt><dd>${esc(run.manifest.tools.join(', ') || 'none')}</dd></dl>
    <p class="brief">${esc(run.manifest.brief)}</p>`;
  forge.setStates(stageStates(run));
  forge.setScore(last.overall_score);
  select(state.stage);
  resetChat();
}

async function refreshRuns(pick) {
  const runs = await api('/api/runs');
  $('#run').innerHTML = runs.map((r) => `<option value="${esc(r.name)}">${esc(r.name)} · ${r.passed}/${r.total}</option>`).join('');
  if (!runs.length) {
    $('#panel').innerHTML = '<div class="alert">No finished runs yet. Forge your first agent.</div>';
    return;
  }
  const name = runs.some((r) => r.name === pick) ? pick : runs[0].name;
  $('#run').value = name;
  await loadRun(name);
}
const fail = (err) => { $('#panel').innerHTML = `<div class="alert bad">${esc(err.message)}. Is the API running? Start it with <code>forge ui</code>.</div>`; };
$('#run').addEventListener('change', (e) => loadRun(e.target.value).catch(fail));

// ---------------------------------------------------------------- chat
function resetChat() {
  const run = state.run;
  $('#chat-agent').textContent = `${run.agent.name} · v${run.agent.version}`;
  $('#messages').innerHTML = '';
  const pickType = (t) => run.evals.cases.find((c) => c.type === t)?.question;
  const ideas = [pickType('tool') || pickType('answerable'), pickType('multi_doc'), pickType('out_of_scope')].filter(Boolean);
  $('#suggestions').innerHTML = ideas.map((q) => `<button type="button">${esc(q)}</button>`).join('');
}
$('#suggestions').addEventListener('click', (e) => {
  const b = e.target.closest('button');
  if (b) { $('#q').value = b.textContent; $('#ask').requestSubmit(); }
});
function bubble(cls, html) {
  const d = document.createElement('div');
  d.className = `msg ${cls}`;
  d.innerHTML = html;
  $('#messages').appendChild(d);
  d.scrollIntoView({ block: 'end' });
  return d;
}
$('#ask').addEventListener('submit', async (e) => {
  e.preventDefault();
  const q = $('#q').value.trim();
  const send = $('#ask button');
  if (!q || !state.run || send.disabled) return;
  $('#q').value = '';
  send.disabled = true;
  bubble('user', esc(q));
  const pending = bubble('bot pending', 'Thinking…');
  const name = state.run.name;
  forge.setBusy(true);
  try {
    const r = await api(`/api/runs/${encodeURIComponent(name)}/chat`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: q, history: state.history }) });
    state.history.push({ role: 'user', content: q }, { role: 'assistant', content: r.answer });
    pending.className = `msg bot ${r.refused ? 'refused' : ''}`;
    pending.innerHTML = `${r.refused ? '<span class="chip warn">refused</span> ' : ''}${esc(r.answer)}
      <p class="muted">Sources: ${esc(r.citations.join(', ') || 'none')}</p>
      <details><summary>Trace · ${r.seconds.toFixed(1)}s</summary>
      ${r.tool_calls.map((t) => `<p><span class="chip ok">${esc(t.tool)}</span> <code>${esc(JSON.stringify(t.args))}</code></p><pre>${esc(t.result)}</pre>`).join('')}
      <p class="muted">Retrieved: ${esc(r.retrieved.join(', '))}</p>${r.error ? `<p class="bad">${esc(r.error)}</p>` : ''}</details>`;
  } catch (err) {
    pending.className = 'msg bot error';
    pending.textContent = err.message;
  } finally {
    send.disabled = false;
    forge.setBusy(false);
  }
});
$('#open-chat').addEventListener('click', () => { $('#chat').hidden = false; $('#q').focus(); });

// ---------------------------------------------------------------- build
$('#open-build').addEventListener('click', () => $('#build').showModal());
const builderHeaders = () => ({ 'X-Access-Code': $('#code').value });
api('/api/config').then((c) => {
  $('#code-field').hidden = !c.needs_code;
  if (!c.build_enabled) {
    $('#open-build').disabled = true;
    $('#open-build').title = 'Building is switched off on this public demo. Clone the repository to forge your own.';
  }
}).catch(() => {});

let reviewing = null;
async function decide(approved) {
  let requirements = null;
  try {
    if (approved) requirements = JSON.parse($('#review-json').value);
    await api(`/api/jobs/${reviewing}/approve`, { method: 'POST', headers: { 'Content-Type': 'application/json', ...builderHeaders() }, body: JSON.stringify({ approved, requirements }) });
    $('#review').hidden = true;
    reviewing = null;
  } catch (err) {
    $('#job-status').textContent = err instanceof SyntaxError ? `The JSON is not valid: ${err.message}` : err.message;
  }
}
$('#approve').addEventListener('click', () => decide(true));
$('#reject').addEventListener('click', () => decide(false));
document.querySelectorAll('[data-close]').forEach((b) => b.addEventListener('click', () => {
  const el = document.getElementById(b.dataset.close);
  if (el.close) el.close(); else el.hidden = true;
}));
$('#build-form [name=cases]').addEventListener('input', (e) => { $('#cases-out').textContent = e.target.value; });

async function poll(id) {
  try {
    const job = await api(`/api/jobs/${id}`);
    if (job.status === 'awaiting_approval' && reviewing !== job.id) {
      reviewing = job.id;
      $('#review').hidden = false;
      $('#review-json').value = JSON.stringify(job.requirements, null, 2);
      $('#review-guard').innerHTML = job.groundability.map((g) => `<span class="chip ${{ supported: 'ok', partial: 'warn', unsupported: 'bad' }[g.status]}">${esc(g.topic)}: ${esc(g.status)}</span>`).join(' ');
    }
    if (job.status === 'running') $('#job-status').textContent = `Stage ${job.stage || 1} of 7`;
    else $('#job-status').textContent = job.status.replace('_', ' ');
    $('#job-log').textContent = [...job.events, job.error].filter(Boolean).join('\n');
    $('#job-log').scrollTop = $('#job-log').scrollHeight;
    forge.setStates(STAGES.map((_, i) => (job.status === 'done' || i + 1 < job.stage ? 'done' : i + 1 === job.stage ? 'active' : 'idle')));
    if (job.stage) forge.select(job.stage - 1);
    if (job.status === 'done' || job.status === 'failed') {
      forge.setBusy(false);
      $('#forge-btn').disabled = false;
      $('#review').hidden = true;
      if (job.status === 'done') { $('#build').close(); await refreshRuns(job.name); }
      return;
    }
  } catch (err) {
    $('#job-status').textContent = err.message;
  }
  setTimeout(() => poll(id), 2000);
}

$('#build-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  $('#forge-btn').disabled = true;
  $('#job').hidden = false;
  $('#job-status').textContent = 'Uploading…';
  $('#job-log').textContent = '';
  try {
    const job = await api('/api/build', { method: 'POST', headers: builderHeaders(), body: new FormData(e.target) });
    forge.setBusy(true);
    poll(job.id);
  } catch (err) {
    $('#job-status').textContent = err.message;
    $('#forge-btn').disabled = false;
  }
});

refreshRuns().catch(fail);

// One view per factory stage. Everything shown comes from the run's artifacts; all text is escaped.
import { marked } from 'marked';
import DOMPurify from 'dompurify';

export const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const pct = (x) => `${Math.round(x * 100)}%`;
export const finalIteration = (run) => run.iterations.filter((i) => i.accepted).at(-1);

export function wilson(k, n, z = 1.96) {
  if (!n) return [0, 0];
  const p = k / n, d = 1 + (z * z) / n, c = p + (z * z) / (2 * n);
  const m = z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n));
  return [Math.max(0, (c - m) / d), Math.min(1, (c + m) / d)];
}

const head = (title, sub) => `<header class="view-head"><h2>${title}</h2><p class="muted">${sub}</p></header>`;
const chip = (text, tone = '') => `<span class="chip ${tone}">${esc(text)}</span>`;

function documents(run) {
  const cards = run.profile.docs.map((d) => `
    <article class="card">
      <h3>${esc(d.doc_id)}</h3>
      <p>${chip(d.kind)} ${chip(`${d.n_words} words`)} ${d.n_rows != null ? chip(`${d.n_rows} rows`) : ''}</p>
      <p class="muted">${esc((d.columns.length ? d.columns : d.headings).slice(0, 12).join(' · '))}</p>
      ${d.warnings.map((w) => `<p class="bad">${esc(w)}</p>`).join('')}
    </article>`).join('');
  return head('Documents', 'A deterministic profile of the corpus. Later stages reason over this.') + `<div class="grid">${cards}</div>`;
}

function interview(run) {
  const grounded = new Map(run.questions.questions.map((q) => [q.question, q.grounded_in]));
  const items = run.requirements.qa.map((x) => `
    <article class="card">
      <h3>${esc(x.question)}</h3>
      <p>${esc(x.answer)}</p>
      <p>${chip(x.source === 'user' ? 'answered by a person' : 'conservative default', x.source === 'user' ? 'ok' : '')} ${(grounded.get(x.question) || []).slice(0, 5).map((t) => chip(t, 'term')).join(' ')}</p>
    </article>`).join('');
  return head('Intake interview', `${pct(run.questions.grounded_share)} of the questions name something that really exists in the documents.`) + `<div class="grid">${items}</div>`;
}

function guard(run) {
  const tone = { supported: 'ok', partial: 'warn', unsupported: 'bad' };
  const rows = run.requirements.groundability.map((g) => `
    <tr><td>${esc(g.topic)}</td><td>${chip(g.status, tone[g.status])}</td>
    <td><div class="meter" title="lexical coverage"><i style="width:${g.lexical_coverage * 100}%"></i></div></td>
    <td class="muted">${esc(g.note)}</td></tr>`).join('');
  const missing = run.requirements.ungrounded_topics;
  return head('Groundability guard', 'Can the documents actually support what the brief asks for?')
    + (missing.length ? `<div class="alert"><strong>Not in the documents:</strong> ${missing.map(esc).join(', ')}. The agent is told to decline these instead of inventing answers.</div>` : '<div class="alert ok">No requested topic was flagged as unsupported.</div>')
    + `<div class="scroll"><table><thead><tr><th>Topic</th><th>Status</th><th>Word coverage</th><th>Note</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function agent(run) {
  const a = run.agent, r = a.retrieval;
  const tools = a.tools.length
    ? a.tools.map((t) => `<article class="card accent"><h3>${esc(t.name)}</h3><p class="muted">Justified by</p><blockquote>${esc(t.justification)}</blockquote></article>`).join('')
    : '<article class="card"><h3>No tools</h3><p class="muted">Nothing in the brief needs one. An unnecessary tool counts as a defect.</p></article>';
  const dropped = [...(a.dropped_tools || []).map((d) => `<li><b>${esc(d.tool)}</b>: ${esc(d.reason)}</li>`),
    ...(a.dropped_rules || []).map((d) => `<li><i>${esc(d.rule)}</i><br><span class="muted">${esc(d.reason)}</span></li>`)].join('');
  return head(`Agent definition · v${a.version}`, `${esc(a.model)} · chunk ${r.chunk_size}/${r.chunk_overlap} words · top-k ${r.top_k} · ${esc(r.mode)}${r.query_rewrite ? ' · query rewrite' : ''}${r.rerank ? ' · rerank' : ''}`)
    + `<div class="grid">${tools}</div><h3>Prompt rules</h3><ol class="rules">${a.rules.map((x) => `<li>${esc(x.text)} ${x.added_in_iteration ? chip(`added in iteration ${x.added_in_iteration}`, 'warn') : ''}</li>`).join('')}</ol>`
    + (dropped ? `<details><summary>Held back by the gates</summary><ul>${dropped}</ul></details>` : '')
    + `<details><summary>Declarative definition (YAML)</summary><pre>${esc(run.agent_yaml)}</pre></details>`;
}

function exam(run) {
  const results = new Map(finalIteration(run).results.map((r) => [r.case_id, r]));
  const types = [...new Set(run.evals.cases.map((c) => c.type))];
  const items = run.evals.cases.map((c) => {
    const r = results.get(c.id);
    if (!r) return '';
    return `<details class="case ${r.passed ? 'pass' : 'fail'}" data-type="${esc(c.type)}" data-pass="${r.passed}">
      <summary><span class="dot"></span>${esc(c.question)}<span class="tags">${chip(c.type)} ${chip(c.split, c.split === 'holdout' ? 'term' : '')}</span></summary>
      <p><b>Agent:</b> ${esc(r.answer)}</p>
      <p><b>Expected:</b> ${c.expected_refusal ? 'refusal' : c.key_facts.map((f) => chip(f, 'term')).join(' ')}</p>
      ${r.failure || r.judge_note ? `<p class="muted"><b>Judge:</b> ${esc(r.failure)} ${esc(r.judge_note)}</p>` : ''}
    </details>`;
  }).join('');
  const s = run.evals.stats;
  return head('Exam', `${s.kept} cases kept of ${s.proposed} proposed. ${s.dropped_unverified} discarded because their facts were not in the source.`)
    + `<div class="filters" id="filters"><button class="on" data-f="all">All</button><button data-f="fail">Failures</button>${types.map((t) => `<button data-f="${esc(t)}">${esc(t.replace('_', ' '))}</button>`).join('')}</div><div>${items}</div>`;
}

function chart(iterations) {
  const W = 640, H = 220, L = 40, B = 28, T = 12;
  const x = (i) => L + (iterations.length === 1 ? (W - L - 16) / 2 : (i * (W - L - 16)) / (iterations.length - 1));
  const y = (v) => T + (1 - v) * (H - T - B);
  const line = (key, cls) => `<polyline class="${cls}" points="${iterations.map((it, i) => `${x(i)},${y(it[key])}`).join(' ')}"/>`
    + iterations.map((it, i) => `<circle class="${cls} ${it.accepted ? '' : 'rolled'}" cx="${x(i)}" cy="${y(it[key])}" r="4"><title>iteration ${it.iteration}: ${pct(it[key])}${it.accepted ? '' : ' (rolled back)'}</title></circle>`).join('');
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Score per iteration">
    ${[0, 0.25, 0.5, 0.75, 1].map((v) => `<line class="gridline" x1="${L}" x2="${W - 8}" y1="${y(v)}" y2="${y(v)}"/><text x="4" y="${y(v) + 4}">${pct(v)}</text>`).join('')}
    ${iterations.map((it, i) => `<text x="${x(i)}" y="${H - 8}" text-anchor="middle">${i === 0 ? 'baseline' : `iter ${it.iteration}`}</text>`).join('')}
    ${line('overall_score', 'l-all')}${line('dev_score', 'l-dev')}${line('holdout_score', 'l-hold')}
  </svg><p class="legend"><span class="l-all">overall</span><span class="l-dev">dev (optimizer sees)</span><span class="l-hold">hold-out (never seen)</span><span class="rolled-key">hollow = rolled back</span></p>`;
}

function optimizer(run) {
  const log = run.iterations.slice(1).map((it) => `
    <article class="card ${it.accepted ? 'accent' : 'dim'}">
      <h3>Iteration ${it.iteration} ${chip(it.accepted ? 'kept' : 'rolled back', it.accepted ? 'ok' : 'bad')}</h3>
      <p class="muted">${esc(it.note)}</p>
      ${it.changes.map((c) => `<p>${chip(c.category, 'warn')} ${esc(c.detail)}<br><span class="muted">targeted: ${esc(c.addresses.join(', '))}</span></p>`).join('')}
    </article>`).join('');
  return head('Critic and optimizer', 'One targeted fix per failure class. A change stays only if it earns its place.')
    + chart(run.iterations) + (log ? `<div class="grid">${log}</div>` : '<div class="alert">No change was applied: there were no development-split failures to target.</div>');
}

function report(run) {
  const md = (t) => DOMPurify.sanitize(marked.parse(t));
  return head('Honest report', 'Written by the factory, including what it cannot prove.')
    + (run.note ? `<div class="alert warn md">${md(run.note)}</div>` : '') + `<article class="md">${md(run.report)}</article>`;
}

export const STAGES = [
  { title: 'Documents', view: documents },
  { title: 'Interview', view: interview },
  { title: 'Guard', view: guard },
  { title: 'Agent', view: agent },
  { title: 'Exam', view: exam },
  { title: 'Optimizer', view: optimizer },
  { title: 'Report', view: report },
];

export function stageStates(run) {
  const last = finalIteration(run);
  const missing = run.requirements.ungrounded_topics.length;
  return ['done', 'done', missing ? 'warn' : 'done', 'done', last.n_pass < last.n_total ? 'warn' : 'done', run.iterations.some((i) => !i.accepted) ? 'warn' : 'done', 'done'];
}

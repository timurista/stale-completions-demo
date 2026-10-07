"""Builds review.html, a local-only stepper over the real trace (trace.json) and results.json.
Nothing is typed in by hand: every state on the page comes from those files. Run after experiment.py:
  python3 build_review.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
trace = json.loads((HERE / "trace.json").read_text())
results = json.loads((HERE / "results.json").read_text())
fixtures = json.loads((HERE / "fixtures.json").read_text())
data = {"trace": trace, "results": results, "fixtures": fixtures}

HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Stale Completion Stepper</title>
<style>
  :root { --ink:#0b0f14; --panel:#0f141b; --line:#1e2733; --fg:#e8edf3; --muted:#9aa6b5; --faint:#7c8898; --teal:#35d0b0; --rose:#ef7a6d; color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--ink); color:var(--fg); font:15px/1.5 Inter, -apple-system, system-ui, sans-serif; }
  main { max-width: 1120px; margin: 0 auto; padding: 24px 16px 60px; }
  .mono { font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace; }
  .kicker { font: 600 12px 'JetBrains Mono', ui-monospace, monospace; letter-spacing:.12em; text-transform:uppercase; color:var(--teal); }
  h1 { font-size: 26px; margin: 6px 0 4px; letter-spacing:-.01em; }
  p.sub { color: var(--muted); margin: 0 0 18px; max-width: 760px; }
  .synthetic { display:inline-block; border:1px solid var(--line); border-radius:6px; padding:2px 8px; color:var(--muted); font-size:12px; }
  .controls { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin: 16px 0; }
  select, button { font: inherit; color: var(--fg); background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 8px 12px; min-height: 40px; }
  button:disabled { opacity: .4; }
  .tick { font-family: 'JetBrains Mono', monospace; color: var(--muted); }
  .note { color: var(--muted); font-size: 14px; margin: 0 0 14px; }
  .event { background: var(--panel); border:1px solid var(--line); border-radius: 12px; padding: 12px 14px; margin-bottom: 14px; }
  .grid { display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 12px; }
  @media (max-width: 860px) { .grid { grid-template-columns: 1fr; } }
  .col { background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 14px; min-width: 0; }
  .col h2 { font-size: 15px; margin: 0 0 2px; }
  .col .desc { color: var(--faint); font-size: 12.5px; margin-bottom: 10px; }
  .state { border-radius: 10px; padding: 10px 12px; border: 1px solid var(--line); margin-bottom: 10px; }
  .state .lbl { font: 600 11px 'JetBrains Mono', monospace; letter-spacing: .1em; text-transform: uppercase; }
  .state.current { border-color: #1f6f63; } .state.current .lbl { color: var(--teal); }
  .state.pending .lbl, .state.cancelled .lbl { color: var(--muted); }
  .state.conflict { border-color: #7a3c35; } .state.conflict .lbl { color: var(--rose); }
  .state.wrong { outline: 2px solid var(--rose); outline-offset: 2px; }
  .payload { margin-top: 4px; font-size: 14px; overflow-wrap:anywhere; }
  .action { font-size: 13px; color: var(--muted); margin-bottom: 8px; overflow-wrap:anywhere; }
  .action b { color: var(--fg); }
  ul.hist { list-style:none; padding:0; margin:0; font-size: 12.5px; }
  ul.hist li { display:flex; gap:8px; padding: 4px 0; border-top: 1px solid var(--line); overflow-wrap:anywhere; }
  .tag { font: 600 10.5px 'JetBrains Mono', monospace; text-transform: uppercase; letter-spacing:.06em; padding: 1px 6px; border-radius: 5px; border:1px solid var(--line); white-space: nowrap; }
  .tag.admitted { color: var(--teal); } .tag.superseded, .tag.cancelled, .tag.duplicate { color: var(--muted); }
  .tag.held-conflict, .tag.rejected-mismatch { color: var(--rose); }
  .verdict { font-size: 13px; margin-top: 10px; color: var(--muted); }
  .verdict.bad { color: var(--rose); } .verdict.good { color: var(--teal); }
  footer { color: var(--faint); font-size: 12.5px; margin-top: 22px; max-width: 760px; }
</style>
</head>
<body>
<main>
  <div class="kicker">Local review · synthetic schedules</div>
  <h1>When the agent finishes yesterday's task</h1>
  <p class="sub">Each step replays one event from <span class="mono">trace.json</span>. The same schedule feeds all three policies. <span class="synthetic">Authored synthetic inputs · ticks are ordering, not time</span></p>
  <div class="controls">
    <select id="case" aria-label="Case"></select>
    <button id="prev" aria-label="Previous step">◀ Prev</button>
    <span class="tick" id="pos"></span>
    <button id="next" aria-label="Next step">Next ▶</button>
  </div>
  <p class="note" id="note"></p>
  <div class="event" id="event"></div>
  <div class="grid" id="grid"></div>
  <footer>States: Current (teal), Pending, Cancelled, Conflict (rose). A rose outline marks a view that differs from the frozen expectation at the end of the case. This page models one local authority; it is not a production UI and not a distributed-systems proof.</footer>
</main>
<script>
const DATA = __DATA__;
const POL = [
  ['naive', 'Overwrite on arrival', 'Newest result wins.'],
  ['broken_guard', 'Check, then write later', 'Checks the decision on arrival, writes without rechecking.'],
  ['corrected', 'Check at the write', 'Checks and writes in one step against the current decision.'],
];
const sel = document.getElementById('case');
for (const c of DATA.fixtures.cases) { const o = document.createElement('option'); o.value = c.case; o.textContent = c.title; sel.append(o); }
const params = new URLSearchParams(location.search);
if (params.get('case')) sel.value = params.get('case');
let step = Number(params.get('step') || 0);

function rows(caseId, policy) { return DATA.trace.filter(r => r.case === caseId && r.policy === policy); }
function steps(caseId) {
  // A shared timeline of (tick, event) from the corrected run; the broken guard's extra "check" row is shown inside its column.
  return rows(caseId, 'corrected').map(r => ({ tick: r.tick, key: r.key, event: r.event, ref: r.completion || r.decision || r.job || '' }));
}
function el(tag, cls, text) { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; }

function draw() {
  const cid = sel.value;
  const tl = steps(cid);
  step = Math.max(0, Math.min(step, tl.length - 1));
  const s = tl[step];
  const fx = DATA.fixtures.cases.find(c => c.case === cid);
  document.getElementById('note').textContent = fx.note;
  document.getElementById('pos').textContent = `step ${step + 1}/${tl.length} · tick ${s.tick}`;
  document.getElementById('prev').disabled = step === 0;
  document.getElementById('next').disabled = step === tl.length - 1;
  const src = fx.events.find(e => e.tick === s.tick && e.key === s.key);
  const ev = document.getElementById('event');
  ev.replaceChildren();
  const desc = {
    decide: e => `${e.kind === 'cancel' ? 'User cancels' : e.kind === 'resolution' ? 'Explicit resolution' : e.parents.length ? 'User changes the goal' : 'Goal recorded'} · ${e.key} → ${e.decision}${e.parents.length ? ` (replaces ${e.parents.join(' + ')})` : ''}${e.adopt ? `, adopts ${e.adopt}` : ''}`,
    start: e => `Worker starts ${e.job} for ${e.decision}: “${e.content}”`,
    complete: e => `Result ${e.completion} arrives from ${e.job}: “${e.payload}”${e.check_tick !== undefined ? ` (the guard checked at tick ${e.check_tick})` : ''}`,
    external: e => `Outside the authority: ${e.note}`,
  };
  ev.append(el('div', 'mono', `tick ${s.tick}`), el('div', null, src ? desc[src.type](src) : s.event));

  const grid = document.getElementById('grid');
  grid.replaceChildren();
  for (const [p, title, sub] of POL) {
    const rs = rows(cid, p).filter(r => r.tick <= s.tick && (r.tick < s.tick || r.event !== 'check' || true));
    const upto = rows(cid, p).filter(r => r.tick < s.tick || (r.tick === s.tick && rows(cid, p).indexOf(r) <= rows(cid, p).findIndex(x => x.tick === s.tick && x.event === s.event && x.key === s.key)));
    const last = upto.filter(r => r.event !== 'check').at(-1) || upto.at(-1);
    const col = el('section', 'col');
    col.append(el('h2', null, title), el('div', 'desc', sub));
    const keys = [...new Set(DATA.trace.filter(r => r.case === cid).map(r => r.key))];
    const res = DATA.results.cases.find(c => c.case === cid).policies[p];
    const isEnd = step === tl.length - 1;
    for (const k of keys) {
      const kr = upto.filter(r => r.key === k).at(-1);
      const view = kr ? kr.view_after : { status: 'pending', active: null };
      const box = el('div', `state ${view.status}`);
      if (isEnd && !res.view_meets_desired && JSON.stringify(res.final[k]) !== JSON.stringify(DATA.results.cases.find(c => c.case === cid).policies.corrected.final[k])) box.classList.add('wrong');
      box.append(el('div', 'lbl', `${k} · ${view.status}`));
      const pay = view.active ? (res.history.find(h => h.completion === view.active && h.outcome === 'admitted') || res.history.find(h => h.completion === view.active)) : null;
      const shown = view.active ? (upto.filter(r => r.key === k && r.event === 'complete' && r.completion === view.active && r.action === 'admitted').length ? null : null) : null;
      box.append(el('div', 'payload', view.active ? `${view.active}: ${latestPayload(res, view.active, upto)}` : view.status === 'conflict' ? 'No active value until resolved' : view.status === 'cancelled' ? 'No active value' : 'Waiting for a current result'));
      col.append(box);
    }
    if (last && last.key === s.key) {
      const a = el('div', 'action');
      a.append(el('b', null, last.action), document.createTextNode(` · ${last.reason}`));
      col.append(a);
    }
    const hist = el('ul', 'hist');
    const seen = res.history.filter(h => h.tick <= s.tick && (h.tick < s.tick || upto.some(r => r.event === 'complete' && r.tick === h.tick && r.completion === h.completion)));
    for (const h of seen) {
      const li = el('li');
      li.append(el('span', `tag ${h.outcome}`, h.outcome), el('span', null, `${h.completion} (${h.decision}) “${h.payload}”`));
      hist.append(li);
    }
    if (seen.length) col.append(el('div', 'desc', 'Every result received (nothing is deleted):'), hist);
    if (isEnd) col.append(el('div', `verdict ${res.view_meets_desired ? 'good' : 'bad'}`, res.view_meets_desired ? 'End state matches the frozen expectation.' : `End state differs: ${res.desired_mismatches[0]}`));
    grid.append(col);
  }
  const u = new URL(location.href); u.searchParams.set('case', cid); u.searchParams.set('step', step); history.replaceState(null, '', u);
}
function latestPayload(res, comp, upto) {
  const adm = res.history.filter(h => h.completion === comp && upto.some(r => r.event === 'complete' && r.completion === comp && r.tick === h.tick));
  return (adm.at(-1) || res.history.find(h => h.completion === comp)).payload;
}
sel.addEventListener('change', () => { step = 0; draw(); });
document.getElementById('prev').addEventListener('click', () => { step--; draw(); });
document.getElementById('next').addEventListener('click', () => { step++; draw(); });
document.addEventListener('keydown', (e) => { if (e.key === 'ArrowRight') { step++; draw(); } if (e.key === 'ArrowLeft') { step--; draw(); } });
draw();
</script>
</body>
</html>
"""

(HERE / "review.html").write_text(HTML.replace("__DATA__", json.dumps(data, separators=(",", ":"))))
print("review.html written")

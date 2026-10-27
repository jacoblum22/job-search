"""Generate the static HTML dashboard from the jobs DB.

Regenerated fresh on every aggregator run, and after the tailoring packet,
approve and outcome steps so application status stays current. No server required — just open
the file in a browser. Sorting/filtering happens client-side in vanilla JS
against an embedded JSON blob, so it works offline.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from src.db import grouped_jobs
from src.search_match import INTERNSHIP_TITLE_RE as _INTERNSHIP_RE
from src.tailor import store

_APP_LABELS = {
    "shortlisted": "Drafting",
    "ready_for_review": "Ready for review",
    "needs_fixes": "Needs fixes",
    "approved": "Approved, not applied",
    "applied": "Applied",
}
# Sorts applications by how much they need you: fixes first, applied last.
_APP_ORDER = ["needs_fixes", "ready_for_review", "approved", "shortlisted", "applied"]
# Applications waiting on you; they stay at the top of the table whatever it is sorted by.
_NEEDS_YOU = _APP_ORDER[:3]
_FLAG_LABELS = {"weaker_fit": "Weaker fit", "ats_below_floor": "ATS below 70",
                "wide_gap": "ATS 10+ under reachable"}

_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="300">
<title>Job Aggregator Dashboard</title>
<style>
  :root {
    --bg: #0f1115; --panel: #171a21; --border: #2a2e38; --text: #e6e8ec;
    --muted: #9aa1ad; --accent: #5b8cff; --new: #3a7d44; --applied: #b8860b;
    --dismissed: #55586a;
  }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: -apple-system, Segoe UI, sans-serif; background: var(--bg); color: var(--text); }
  header { padding: 20px 24px; border-bottom: 1px solid var(--border); }
  h1 { margin: 0 0 4px; font-size: 20px; }
  .meta { color: var(--muted); font-size: 13px; }
  header { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap; }
  .runbox { display: flex; gap: 8px; align-items: center; font-size: 13px; color: var(--muted); flex-wrap: wrap; }
  .runbox[hidden] { display: none; }
  .runbox input { width: 56px; }
  .runbox button { background: var(--accent); border: 0; color: #fff; padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 13px; }
  .runbox button:disabled { background: var(--dismissed); cursor: default; }
  .runbox .runstate { flex-basis: 100%; text-align: right; max-width: 420px; }
  .controls { display: flex; gap: 12px; flex-wrap: wrap; padding: 16px 24px; border-bottom: 1px solid var(--border); align-items: center; }
  input, select { background: var(--panel); border: 1px solid var(--border); color: var(--text); padding: 6px 10px; border-radius: 6px; font-size: 13px; }
  input[type=text] { min-width: 240px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--border); vertical-align: top; }
  th { cursor: pointer; user-select: none; color: var(--muted); font-weight: 600; position: sticky; top: 0; background: var(--bg); white-space: nowrap; }
  th:hover { color: var(--text); }
  tr:hover td { background: var(--panel); }
  tr.pinned td:first-child { box-shadow: inset 3px 0 0 var(--accent); }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; margin: 1px 2px 1px 0; }
  .src { background: var(--panel); border: 1px solid var(--border); color: var(--muted); }
  .status-new { background: var(--new); }
  .status-applied { background: var(--applied); }
  .status-dismissed { background: var(--dismissed); }
  .status-expired { background: var(--dismissed); }
  .closed { background: none; border: 1px solid #b23b3b; color: #e07070; }
  .due { white-space: nowrap; }
  .muted { color: var(--muted); }
  .due-soon { background: #b23b3b; color: #fff; }
  .due-week { background: none; border: 1px solid #c8932f; color: #e0b050; }
  .app-shortlisted, .app-ready_for_review { background: var(--accent); }
  .app-needs_fixes { background: #b23b3b; }
  .app-approved { background: var(--new); }
  .app-applied { background: var(--applied); }
  .flag { background: none; border: 1px solid #c9a227; color: #e0c060; }
  .applinks { font-size: 12px; margin-top: 2px; }
  .applinks a { margin-right: 8px; }
  .cat-vancouver { background: var(--new); }
  .cat-remote { background: var(--accent); }
  .cat-other { background: var(--dismissed); }
  .tier-A { background: var(--new); }
  .tier-B { background: var(--accent); }
  .tier-C { background: var(--panel); border: 1px solid var(--border); }
  .tier-D, .tier-skip { background: var(--dismissed); }
  .score { white-space: nowrap; cursor: help; }
  label.chk { color: var(--muted); font-size: 13px; display: flex; gap: 6px; align-items: center; }
  .wrap { max-width: 1400px; margin: 0 auto; }
  #count { color: var(--muted); font-size: 13px; margin-left: auto; }
  .tabs { display: flex; gap: 4px; padding: 12px 24px 0; border-bottom: 1px solid var(--border); }
  .tab { background: none; border: 1px solid transparent; border-bottom: none; color: var(--muted); padding: 8px 16px; font-size: 14px; cursor: pointer; border-radius: 6px 6px 0 0; }
  .tab:hover { color: var(--text); }
  .tab.active { color: var(--text); background: var(--panel); border-color: var(--border); font-weight: 600; margin-bottom: -1px; }
  .tab .n { color: var(--muted); font-weight: 400; margin-left: 6px; }
  td.notice { text-align: center; color: var(--muted); padding: 48px 12px; font-size: 14px; }
  td.notice button { margin-left: 8px; background: var(--panel); border: 1px solid var(--border); color: var(--accent); padding: 4px 10px; border-radius: 6px; cursor: pointer; font-size: 13px; }
  td.notice.error { color: #e57373; }
  #statsView { padding: 24px; display: grid; grid-template-columns: repeat(12, 1fr); gap: 18px; }
  #statsView[hidden] { display: none; }
  .card { grid-column: span 6; background: linear-gradient(180deg, #1a1e27 0%, #161920 100%); border: 1px solid #262b36;
          border-radius: 14px; padding: 20px 22px; box-shadow: 0 1px 0 rgba(255,255,255,.03) inset, 0 8px 24px rgba(0,0,0,.25); }
  .card.third { grid-column: span 4; } .card.wide { grid-column: 1 / -1; }
  @media (max-width: 1100px) { .card, .card.third { grid-column: 1 / -1; } }
  .card h2 { font-size: 15px; margin: 0 0 2px; font-weight: 600; letter-spacing: .1px; }
  .card .sub { color: var(--muted); font-size: 12px; margin-bottom: 18px; }
  .kpis { grid-column: 1 / -1; display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 14px; }
  .kpi { background: linear-gradient(180deg, #1a1e27 0%, #161920 100%); border: 1px solid #262b36; border-radius: 14px;
         padding: 16px 18px; position: relative; overflow: hidden; }
  .kpi::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--c, var(--accent)); }
  .kpi b { display: block; font-size: 30px; font-weight: 700; letter-spacing: -.5px; font-variant-numeric: tabular-nums; }
  .kpi span { color: var(--muted); font-size: 12px; }
  .donut { display: flex; gap: 28px; align-items: center; flex-wrap: wrap; }
  .donut svg path { transition: opacity .15s, transform .15s; transform-origin: center; cursor: default; }
  .donut svg:hover path { opacity: .45; } .donut svg path:hover { opacity: 1; transform: scale(1.04); }
  .donut .total { font-size: 26px; font-weight: 700; fill: var(--text); } .donut .total-l { font-size: 11px; fill: var(--muted); }
  .legend { font-size: 13px; flex: 1; min-width: 200px; }
  .legend div { display: flex; gap: 10px; align-items: center; padding: 5px 0; border-bottom: 1px solid #222631; }
  .legend div:last-child { border-bottom: none; }
  .legend i { width: 10px; height: 10px; border-radius: 50%; display: inline-block; flex: none; }
  .legend .n { color: var(--muted); margin-left: auto; font-variant-numeric: tabular-nums; }
  .legend .p { color: var(--text); width: 42px; text-align: right; font-variant-numeric: tabular-nums; }
  .hbars { font-size: 13px; }
  .hbars .r { display: grid; grid-template-columns: minmax(90px, 160px) 1fr 44px; gap: 12px; align-items: center; padding: 6px 0; }
  .hbars .r > span:first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #c9ced8; }
  .hbars .track { background: #10131a; border-radius: 999px; height: 10px; overflow: hidden; }
  .hbars .fill { height: 100%; border-radius: 999px; background: linear-gradient(90deg, var(--c, #5b8cff), var(--c2, #8fb0ff)); }
  .hbars .n { text-align: right; color: var(--muted); font-variant-numeric: tabular-nums; }
  .cols { display: flex; align-items: stretch; gap: 10px; height: 200px; border-bottom: 1px solid #2a2e38; padding-top: 8px; }
  .cols .col { flex: 1; display: flex; flex-direction: column; justify-content: flex-end; align-items: center; position: relative; }
  .cols .bar { width: 64%; max-width: 44px; border-radius: 6px 6px 2px 2px; background: linear-gradient(180deg, #86a6ff, #4a6fe0); transition: filter .15s; }
  .cols .col:hover .bar { filter: brightness(1.25); }
  .cols .bar.stack { display: flex; flex-direction: column-reverse; background: none; overflow: hidden; gap: 1px; }
  .cols .seg { min-height: 2px; }
  .collegend { display: flex; flex-wrap: wrap; gap: 16px; font-size: 12px; color: var(--muted); margin: -8px 0 12px; }
  .collegend span { display: flex; align-items: center; gap: 6px; }
  .collegend i { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
  .cols .v { font-size: 11px; color: var(--text); margin-bottom: 4px; font-variant-numeric: tabular-nums; }
  .cols .k { position: absolute; bottom: -20px; font-size: 11px; color: var(--muted); white-space: nowrap; }
  .card.wide:has(.cols) { padding-bottom: 34px; }
  table.mini { font-size: 13px; width: 100%; } table.mini th { position: static; cursor: default; background: none; font-size: 12px; }
  table.mini td, table.mini th { border-bottom: 1px solid #222631; padding: 7px 8px; }
  table.mini tr:hover td { background: none; } table.mini td.num { text-align: right; font-variant-numeric: tabular-nums; color: var(--muted); }
  .share { display: flex; align-items: center; gap: 8px; } .share .track { flex: 1; background: #10131a; border-radius: 999px; height: 6px; overflow: hidden; }
  .share .fill { height: 100%; background: linear-gradient(90deg, #3a7d44, #6fcf7f); border-radius: 999px; }
  .share span { width: 36px; text-align: right; font-variant-numeric: tabular-nums; color: var(--text); }
</style>
</head>
<body>
<div class="wrap">
<header>
  <div>
    <h1>Job Aggregator Dashboard</h1>
    <div class="meta">Generated __GENERATED_AT__ &middot; __TOTAL__ postings across __SOURCES__ sources</div>
  </div>
  <div class="runbox" id="runBox" hidden>
    <label for="runLimit">Jobs</label>
    <input type="number" id="runLimit" min="1" max="10" value="3">
    <button id="runBtn">Run tailoring</button>
    <div class="runstate" id="runState"></div>
  </div>
</header>
<div class="tabs" role="tablist">
  <button class="tab" role="tab" data-tab="fulltime" id="tab-fulltime">Full-time<span class="n"></span></button>
  <button class="tab" role="tab" data-tab="internship" id="tab-internship">Internships<span class="n"></span></button>
  <button class="tab" role="tab" data-tab="stats" id="tab-stats">Stats</button>
</div>
<div id="statsView" hidden></div>
<div id="jobsView">
<div class="controls">
  <input type="text" id="search" placeholder="Search title / company / location...">
  <select id="statusFilter">
    <option value="">All statuses</option>
    <option value="new">New</option>
    <option value="applied">Applied</option>
    <option value="dismissed">Dismissed</option>
    <option value="expired">Expired</option>
    <option value="closed">Closed</option>
    <option value="open">Still open</option>
  </select>
  <select id="appFilter">
    <option value="">All jobs</option>
    <option value="any">Has an application</option>
    <option value="shortlisted">Drafting</option>
    <option value="ready_for_review">Ready for review</option>
    <option value="needs_fixes">Needs fixes</option>
    <option value="approved">Approved, not applied</option>
    <option value="applied">Applied</option>
  </select>
  <select id="sourceFilter">
    <option value="">All sources</option>
  </select>
  <select id="tierFilter">
    <option value="">All tiers</option>
    <option value="A">Tier A (60+)</option>
    <option value="B">Tier B (40-59)</option>
    <option value="C">Tier C (20-39)</option>
    <option value="D">Tier D (&lt;20)</option>
    <option value="skip">Skipped</option>
  </select>
  <label class="chk"><input type="checkbox" id="hideSkipped" checked> Hide skipped</label>
  <label class="chk"><input type="checkbox" id="hideDismissed" checked> Hide dismissed</label>
  <select id="locationFilter">
    <option value="">All locations</option>
    <option value="vancouver">Vancouver-area</option>
    <option value="remote">Remote</option>
    <option value="other">Other</option>
  </select>
  <span id="count"></span>
</div>
<table id="jobsTable">
  <thead>
    <tr>
      <th data-key="score_sort">Score</th>
      <th data-key="title">Title</th>
      <th data-key="company">Company</th>
      <th data-key="location">Location</th>
      <th data-key="location_category">Category</th>
      <th data-key="status">Status</th>
      <th data-key="app_sort">Application</th>
      <th data-key="deadline_sort" title="Red: 3 days or less left. Amber: a week or less.">Deadline</th>
      <th data-key="years_experience">Years Exp</th>
      <th data-key="sourcesStr">Sources</th>
      <th data-key="posted" title="When the job was first posted. Grey: the posting gives no date, so this is the day it was first seen.">Posted</th>
      <th data-key="first_seen">First Seen</th>
    </tr>
  </thead>
  <tbody id="jobsBody"><tr><td class="notice" colspan="12">Loading jobs&hellip;</td></tr></tbody>
</table>
</div>
</div>
<script id="jobs-data" type="application/json">__JOBS_JSON__</script>
<script>
// If anything below throws, say so instead of leaving the "Loading" row up forever.
window.addEventListener('error', e => {
  document.getElementById('jobsBody').innerHTML =
    '<tr><td class="notice error" colspan="12"></td></tr>';
  document.querySelector('#jobsBody td').textContent =
    'The dashboard hit an error and could not show jobs: ' + e.message;
});
const SERVER = __SERVER__;
// Back from a job page the browser shows this page as it was; if something was changed there, reload.
window.addEventListener('pageshow', e => {
  try {
    if (SERVER && sessionStorage.getItem('dashboardStale')) {
      sessionStorage.removeItem('dashboardStale');
      if (e.persisted) location.reload();
    }
  } catch (_) {}
});
// Run tailoring: starts scripts/run_tailoring.ps1 -Limit N on the PC the server runs on.
if (SERVER) {
  const box = document.getElementById('runBox'), btn = document.getElementById('runBtn');
  const state = document.getElementById('runState'), limitEl = document.getElementById('runLimit');
  let timer = null;
  const show = s => {
    btn.disabled = s.running;
    limitEl.max = s.max;
    if (s.running) {
      const what = s.by === 'dashboard' ? `Tailoring ${s.limit} job${s.limit === 1 ? '' : 's'} (started ${new Date(s.started).toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'})})`
                                        : 'The 9:00 tailoring task is running';
      state.textContent = `${what}. It scrapes first, then drafts each job, so it takes a while.` + (s.last_log ? ` Last: ${s.last_log}` : '');
    } else {
      state.textContent = s.last_log ? `Last run: ${s.last_log}` : '';
    }
    clearTimeout(timer);
    if (s.running) timer = setTimeout(refresh, 30000);
  };
  const refresh = () => fetch('/api/tailoring').then(r => r.json()).then(show).catch(() => {});
  btn.addEventListener('click', async () => {
    const n = parseInt(limitEl.value, 10);
    if (!(n >= 1 && n <= parseInt(limitEl.max, 10))) { state.textContent = `Pick 1 to ${limitEl.max} jobs.`; return; }
    btn.disabled = true;
    const r = await fetch('/api/tailoring', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                             body: JSON.stringify({limit: n})});
    const data = await r.json().catch(() => ({}));
    if (r.ok) show(data.result); else { state.textContent = data.error || 'Could not start the run.'; btn.disabled = false; }
  });
  box.hidden = false;
  refresh();
}
const rawJobs = JSON.parse(document.getElementById('jobs-data').textContent);
const jobs = rawJobs.map(j => ({...j, sourcesStr: j.sources.join(', ')}));

const allSources = [...new Set(jobs.flatMap(j => j.sources))].sort();
const sourceFilterEl = document.getElementById('sourceFilter');
for (const s of allSources) {
  const opt = document.createElement('option');
  opt.value = s; opt.textContent = s;
  sourceFilterEl.appendChild(opt);
}

let sortKey = 'score_sort', sortDir = -1;
const NEWEST_FIRST = new Set(['posted', 'first_seen']);
// The page auto-reloads, so keep the chosen tab in the URL hash.
let activeTab = {'#internships': 'internship', '#stats': 'stats'}[location.hash] || 'fulltime';

function updateTabs() {
  document.getElementById('tab-stats').classList.toggle('active', activeTab === 'stats');
  document.getElementById('statsView').hidden = activeTab !== 'stats';
  document.getElementById('jobsView').hidden = activeTab === 'stats';
  for (const t of ['internship', 'fulltime']) {
    const el = document.getElementById('tab-' + t);
    el.classList.toggle('active', t === activeTab);
    el.setAttribute('aria-selected', String(t === activeTab));
    el.querySelector('.n').textContent = jobs.filter(j => j.job_type === t).length;
  }
}
document.querySelectorAll('.tab').forEach(btn => {
  btn.addEventListener('click', () => {
    activeTab = btn.dataset.tab;
    location.hash = {internship: '#internships', stats: '#stats'}[activeTab] || '';
    render();
  });
});

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s ?? '';
  return div.innerHTML;
}

function fileLink(href, text) {
  return /^file:/i.test(href || '') ? `<a href="${escapeHtml(href)}" target="_blank">${text}</a>` : '';
}

function appCell(app) {
  if (!app) return '';
  const flags = app.flags.map(f => `<span class="badge flag">${escapeHtml(f)}</span>`).join('');
  // file: links don't open from an http page; the served dashboard has the details page instead.
  const links = SERVER ? '' : fileLink(app.final_href, 'Files') + fileLink(app.check_href, 'Checklist');
  return `<span class="badge app-${escapeHtml(app.status)}">${escapeHtml(app.label)}</span>${flags}`
    + (links ? `<div class="applinks">${links}</div>` : '');
}

// --- Stats tab (plain SVG and divs, so the page still works offline) -------------
const COLORS = ['#6c8cff', '#4cc38a', '#f2b84b', '#b07cf0', '#f07178', '#45c4d9', '#f0915a', '#8fa0b8', '#9ad46b', '#e57fb4'];
const TIER_COLORS = {A: ['#2f9e5b', '#5fd38b'], B: ['#4a6fe0', '#86a6ff'], C: ['#8a7a3a', '#e0c060'],
                     D: ['#5a5f70', '#8a90a3'], skip: ['#3d404c', '#5f6372']};
const family = s => s.split(':')[0];
const pct = (n, d) => d ? Math.round(100 * n / d) : 0;
const fmt = n => n.toLocaleString();

function countBy(items, key) {
  const m = new Map();
  for (const it of items) { const k = key(it); m.set(k, (m.get(k) || 0) + 1); }
  return [...m.entries()].sort((a, b) => b[1] - a[1]);
}

function donutSvg(entries, label) {
  const total = entries.reduce((a, [, n]) => a + n, 0);
  const R = 90, r = 58, gap = entries.length > 1 ? 0.012 : 0;
  let a0 = -Math.PI / 2, h = '';
  const pt = (rad, a) => `${(rad * Math.cos(a)).toFixed(2)} ${(rad * Math.sin(a)).toFixed(2)}`;
  entries.forEach(([k, n], i) => {
    let a1 = a0 + 2 * Math.PI * n / total;
    if (a1 - a0 >= 2 * Math.PI - 1e-6) a1 = a0 + 2 * Math.PI - 1e-4;  // a full ring
    const s = a0 + gap, e = Math.max(s, a1 - gap), large = e - s > Math.PI ? 1 : 0;
    h += `<path d="M${pt(R, s)} A${R} ${R} 0 ${large} 1 ${pt(R, e)} L${pt(r, e)} A${r} ${r} 0 ${large} 0 ${pt(r, s)} Z"
      fill="${COLORS[i % COLORS.length]}"><title>${escapeHtml(k)}: ${fmt(n)} (${pct(n, total)}%)</title></path>`;
    a0 = a1;
  });
  return `<svg width="200" height="200" viewBox="-100 -100 200 200">${h}
    <text class="total" text-anchor="middle" y="6">${fmt(total)}</text>
    <text class="total-l" text-anchor="middle" y="24">${escapeHtml(label)}</text></svg>`;
}

function donutCard(title, sub, entries, label, cls = '', top = 8) {
  const shown = entries.slice(0, top);
  const rest = entries.slice(top).reduce((a, [, n]) => a + n, 0);
  if (rest) shown.push(['Other', rest]);
  const total = shown.reduce((a, [, n]) => a + n, 0);
  if (!total) return `<div class="card ${cls}"><h2>${title}</h2><div class="sub">${sub}</div><div class="sub">Nothing yet.</div></div>`;
  const legend = shown.map(([k, n], i) => `<div><i style="background:${COLORS[i % COLORS.length]}"></i>${escapeHtml(k)}
    <span class="n">${fmt(n)}</span><span class="p">${pct(n, total)}%</span></div>`).join('');
  return `<div class="card ${cls}"><h2>${title}</h2><div class="sub">${sub}</div>
    <div class="donut">${donutSvg(shown, label)}<div class="legend">${legend}</div></div></div>`;
}

function barsCard(title, sub, entries, cls = '', colorOf = null) {
  const max = Math.max(1, ...entries.map(([, n]) => n));
  const rows = entries.map(([k, n, key]) => {
    const [c, c2] = colorOf ? colorOf(key ?? k) : ['#4a6fe0', '#86a6ff'];
    return `<div class="r"><span title="${escapeHtml(k)}">${escapeHtml(k)}</span>
      <div class="track"><div class="fill" style="width:${Math.max(n ? 2 : 0, 100 * n / max)}%;--c:${c};--c2:${c2}"></div></div>
      <span class="n">${fmt(n)}</span></div>`;
  }).join('');
  return `<div class="card ${cls}"><h2>${title}</h2><div class="sub">${sub}</div>
    <div class="hbars">${rows || '<span class="sub">Nothing yet.</span>'}</div></div>`;
}

// One column per day, stacked by tier (A at the bottom), with a legend.
function stackedColumnsCard(title, sub, days, cls = '') {
  const tiers = ['A', 'B', 'C', 'D', 'skip'];
  const name = t => t === 'skip' ? 'Skipped' : 'Tier ' + t;
  const max = Math.max(1, ...days.map(d => d.total));
  const cols = days.map(d => {
    const tip = [`${d.label}: ${d.total}`, ...tiers.filter(t => d[t]).map(t => `${name(t)} ${d[t]}`)].join('\n');
    const segs = tiers.filter(t => d[t]).map(t =>
      `<div class="seg" style="flex:${d[t]};background:linear-gradient(180deg, ${TIER_COLORS[t][1]}, ${TIER_COLORS[t][0]})"></div>`).join('');
    return `<div class="col" title="${escapeHtml(tip)}"><span class="v">${d.total || ''}</span>
      <div class="bar stack" style="height:${d.total ? Math.max(3, 100 * d.total / max) : 0}%">${segs}</div>
      <span class="k">${escapeHtml(d.label)}</span></div>`;
  }).join('');
  const legend = tiers.map(t => `<span><i style="background:${TIER_COLORS[t][1]}"></i>${name(t)}</span>`).join('');
  return `<div class="card ${cls}"><h2>${title}</h2><div class="sub">${sub}</div>
    <div class="collegend">${legend}</div><div class="cols">${cols}</div></div>`;
}

function sourceOf(j) {
  const fams = [...new Set(j.sources.map(family))];
  return fams.length === 1 ? fams[0] : 'Several sources';
}

function renderStats() {
  const live = jobs.filter(j => j.tier !== 'skip');
  const apps = jobs.filter(j => j.app);
  const good = jobs.filter(j => j.tier === 'A' || j.tier === 'B');
  const week = new Date(Date.now() - 7 * 864e5).toISOString();
  const kpi = (n, label, c) => `<div class="kpi" style="--c:${c}"><b>${fmt(n)}</b><span>${label}</span></div>`;
  let h = `<div class="kpis">
    ${kpi(jobs.length, 'jobs stored', '#8fa0b8')}
    ${kpi(jobs.filter(j => j.tier === 'A').length, 'tier A', '#4cc38a')}
    ${kpi(jobs.filter(j => j.tier === 'B').length, 'tier B', '#6c8cff')}
    ${kpi(jobs.filter(j => (j.first_seen || '') >= week).length, 'new in the last 7 days', '#45c4d9')}
    ${kpi(apps.length, 'tailored applications', '#b07cf0')}
    ${kpi(jobs.filter(j => j.status === 'applied').length, 'applied', '#f2b84b')}
  </div>`;

  // Each job counted once: under its only source, or "Several sources" when more than one board listed it.
  h += donutCard('Where your jobs come from', 'Each job counted once; jobs more than one source listed are grouped',
                 countBy(jobs, sourceOf), 'jobs');
  h += donutCard('Where your A and B jobs come from', 'The same, for tier A and B only', countBy(good, sourceOf), 'A + B jobs');

  const tiers = ['A', 'B', 'C', 'D', 'skip'];
  h += barsCard('Jobs by tier', 'From the score', tiers.map(t => [t === 'skip' ? 'Skipped' : 'Tier ' + t,
                jobs.filter(j => j.tier === t).length, t]), 'third', t => TIER_COLORS[t]);
  const locNames = {vancouver: 'Vancouver area', remote: 'Remote', other: 'Elsewhere'};
  const locColors = {vancouver: ['#2f9e5b', '#5fd38b'], remote: ['#4a6fe0', '#86a6ff'], other: ['#5a5f70', '#8a90a3']};
  h += barsCard('Jobs by location', 'Where the job is based', countBy(jobs, j => j.location_category || 'other')
                .map(([k, n]) => [locNames[k] || k, n, k]), 'third', k => locColors[k] || locColors.other);
  const appOrder = ['needs_fixes', 'ready_for_review', 'approved', 'shortlisted', 'applied'];
  const appLabel = {needs_fixes: 'Needs fixes', ready_for_review: 'Ready for review', approved: 'Approved, not applied',
                    shortlisted: 'Drafting', applied: 'Applied'};
  const appColors = {needs_fixes: ['#b23b3b', '#f07178'], ready_for_review: ['#4a6fe0', '#86a6ff'],
                     approved: ['#2f9e5b', '#5fd38b'], shortlisted: ['#5a5f70', '#8a90a3'], applied: ['#b8860b', '#f2b84b']};
  h += barsCard('Applications', 'Tailored resumes and cover letters by status',
                appOrder.map(s => [appLabel[s], apps.filter(j => j.app.status === s).length, s]), 'third', s => appColors[s]);

  const days = [];
  for (let i = 13; i >= 0; i--) {
    const d = new Date(Date.now() - i * 864e5).toISOString().slice(0, 10);
    const day = jobs.filter(j => (j.first_seen || '').slice(0, 10) === d);
    const row = {label: d.slice(5).replace('-', '/'), total: day.length};
    for (const t of ['A', 'B', 'C', 'D', 'skip']) row[t] = day.filter(j => (j.tier || 'skip') === t).length;
    days.push(row);
  }
  h += stackedColumnsCard('New jobs per day', 'First seen, last 14 days (jobs still stored), by tier', days, 'wide');

  // Which source families find good jobs: share of each family's jobs that are tier A or B.
  const fams = countBy(jobs.flatMap(j => [...new Set(j.sources.map(family))]), f => f);
  const rows = fams.map(([f, n]) => {
    const g = good.filter(j => j.sources.some(s => family(s) === f)).length;
    return `<tr><td>${escapeHtml(f)}</td><td class="num">${fmt(n)}</td><td class="num">${fmt(g)}</td>
      <td><div class="share"><div class="track"><div class="fill" style="width:${pct(g, n)}%"></div></div><span>${pct(g, n)}%</span></div></td></tr>`;
  }).join('');
  h += `<div class="card"><h2>Which sources find good jobs</h2><div class="sub">Jobs each source listed, and the share that are tier A or B</div>
    <table class="mini"><thead><tr><th>Source</th><th style="text-align:right">Jobs</th><th style="text-align:right">A or B</th><th style="width:40%">Share</th></tr></thead>
    <tbody>${rows}</tbody></table></div>`;
  h += barsCard('Companies with the most jobs', 'Top 12, skipped jobs left out',
                countBy(live, j => j.company || 'Unknown').slice(0, 12), '', () => ['#7b5cd6', '#b49af5']);
  document.getElementById('statsView').innerHTML = h;
}

function render() {
  const q = document.getElementById('search').value.toLowerCase();
  const status = document.getElementById('statusFilter').value;
  const source = sourceFilterEl.value;
  const locationCat = document.getElementById('locationFilter').value;
  const tier = document.getElementById('tierFilter').value;
  const hideSkipped = document.getElementById('hideSkipped').checked;
  // Choosing "Dismissed" in the status filter shows them whatever the box says.
  const hideDismissed = document.getElementById('hideDismissed').checked && status !== 'dismissed';
  const appStatus = document.getElementById('appFilter').value;

  updateTabs();
  if (activeTab === 'stats') { renderStats(); return; }
  let filtered = jobs.filter(j => {
    if (j.job_type !== activeTab) return false;
    if (status === 'closed' ? !j.closed : status === 'open' ? j.closed : status && j.status !== status) return false;
    if (appStatus && !(j.app && (appStatus === 'any' || j.app.status === appStatus))) return false;
    if (source && !j.sources.includes(source)) return false;
    if (locationCat && j.location_category !== locationCat) return false;
    if (tier && j.tier !== tier) return false;
    if (hideSkipped && tier !== 'skip' && j.tier === 'skip') return false;
    if (hideDismissed && j.status === 'dismissed') return false;
    if (q) {
      const hay = (j.title + ' ' + j.company + ' ' + j.location).toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  filtered.sort((a, b) => {
    if (a.pin !== b.pin) return a.pin - b.pin;  // applications waiting on you come first
    const av = a[sortKey] ?? '', bv = b[sortKey] ?? '';
    if (av < bv) return -1 * sortDir;
    if (av > bv) return 1 * sortDir;
    return 0;
  });

  const tabJobs = jobs.filter(j => j.job_type === activeTab);
  const skippedHidden = hideSkipped && tier !== 'skip'
    ? tabJobs.filter(j => j.tier === 'skip').length : 0;
  const dismissedHidden = hideDismissed
    ? tabJobs.filter(j => j.status === 'dismissed' && !(hideSkipped && tier !== 'skip' && j.tier === 'skip')).length : 0;
  document.getElementById('count').textContent = `${filtered.length} of ${tabJobs.length} shown`
    + (skippedHidden ? ` \u00b7 ${skippedHidden} skipped hidden` : '')
    + (dismissedHidden ? ` \u00b7 ${dismissedHidden} dismissed hidden` : '');

  const body = document.getElementById('jobsBody');
  if (!filtered.length) {
    let msg, action = '';
    if (!tabJobs.length) {
      msg = 'No jobs in this tab yet.';
    } else if (skippedHidden === tabJobs.length) {
      msg = `All ${tabJobs.length} jobs in this tab are scored as skip, so "Hide skipped" hides them.`;
      action = '<button data-act="showSkipped">Show skipped</button>';
    } else {
      msg = 'No jobs match the current search and filters.';
      action = '<button data-act="clear">Clear filters</button>';
    }
    body.innerHTML = `<tr><td class="notice" colspan="12">${escapeHtml(msg)}${action}</td></tr>`;
    return;
  }
  body.innerHTML = filtered.map(j => {
    const link = j.urls.length ? j.urls[0][1] : '';
    const safeLink = /^https?:\/\//i.test(link) ? link : '';
    const postingLink = safeLink
      ? `<a href="${escapeHtml(safeLink)}" target="_blank" rel="noopener noreferrer">${SERVER ? 'Posting' : escapeHtml(j.title)}</a>`
      : '';
    // Served by scripts/serve.py: the title opens the job's details page.
    const titleCell = SERVER
      ? `<a href="/job/${encodeURIComponent(j.id)}">${escapeHtml(j.title)}</a>`
        + (postingLink ? `<div class="applinks">${postingLink}</div>` : '')
      : (postingLink || escapeHtml(j.title));
    const closedBadge = j.closed ? ` <span class="badge closed" title="Can't apply: ${escapeHtml(j.closed)}">${escapeHtml(j.closed)}</span>` : '';
    const srcBadges = j.sources.map(s => `<span class="badge src">${escapeHtml(s)}</span>`).join('');
    const scoreText = j.tier === 'skip' ? 'skip' : (j.score ?? '');
    return `<tr${j.pin < 99 ? ' class="pinned"' : ''}>
      <td class="score" title="${escapeHtml(j.score_reasons)}"><span class="badge tier-${escapeHtml(j.tier)}">${escapeHtml(j.tier)}</span> ${escapeHtml(String(scoreText))}</td>
      <td>${titleCell}${closedBadge}</td>
      <td>${escapeHtml(j.company)}</td>
      <td>${escapeHtml(j.location)}</td>
      <td><span class="badge cat-${escapeHtml(j.location_category)}">${escapeHtml(j.location_category)}</span></td>
      <td><span class="badge status-${escapeHtml(j.status)}">${escapeHtml(j.status)}</span></td>
      <td>${appCell(j.app)}</td>
      <td class="due">${dueCell(j)}</td>
      <td>${j.years_experience ?? ''}</td>
      <td>${srcBadges}</td>
      <td class="due">${postedCell(j)}</td>
      <td>${escapeHtml(j.first_seen)}</td>
    </tr>`;
  }).join('');
}

// Days from today to a YYYY-MM-DD deadline, counted in the viewer's own calendar days.
function daysLeft(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  const now = new Date();
  return Math.round((new Date(y, m - 1, d) - new Date(now.getFullYear(), now.getMonth(), now.getDate())) / 864e5);
}

// When it was first posted, with its age; grey when that's only the day it was first seen.
function postedCell(j) {
  const ago = -daysLeft(j.posted);
  const age = ago <= 0 ? 'today' : `${ago}d ago`;
  return j.posted_given
    ? `${escapeHtml(j.posted)} <span class="muted">${age}</span>`
    : `<span class="muted" title="The posting gives no date; first seen ${escapeHtml(j.posted)}">${escapeHtml(j.posted)} (seen)</span>`;
}

// The posting's deadline: red with 3 days or less left, amber within a week.
function dueCell(j) {
  if (!j.deadline) return '';
  const [y, m, d] = j.deadline.split('-').map(Number);
  const date = new Date(y, m - 1, d).toLocaleDateString(undefined, {month: 'short', day: 'numeric'});
  const days = daysLeft(j.deadline);
  if (j.closed || days < 0) return `<span class="muted">${escapeHtml(date)}</span>`;
  const left = days === 0 ? 'today' : days === 1 ? 'tomorrow' : `${days} days left`;
  const cls = days <= 3 ? 'due-soon' : days <= 7 ? 'due-week' : 'src';
  return `<span class="badge ${cls}" title="Applications close ${escapeHtml(j.deadline)}">${escapeHtml(date)} · ${left}</span>`;
}

document.querySelectorAll('th[data-key]').forEach(th => {
  th.addEventListener('click', () => {
    const key = th.dataset.key;
    // Dates open newest first; everything else ascending.
    if (sortKey === key) { sortDir *= -1; } else { sortKey = key; sortDir = NEWEST_FIRST.has(key) ? -1 : 1; }
    render();
  });
});

document.getElementById('search').addEventListener('input', render);
document.getElementById('statusFilter').addEventListener('change', render);
document.getElementById('appFilter').addEventListener('change', render);
document.getElementById('locationFilter').addEventListener('change', render);
document.getElementById('tierFilter').addEventListener('change', render);
document.getElementById('hideSkipped').addEventListener('change', render);
document.getElementById('hideDismissed').addEventListener('change', render);
sourceFilterEl.addEventListener('change', render);
document.getElementById('jobsBody').addEventListener('click', e => {
  const act = e.target.dataset && e.target.dataset.act;
  if (act === 'showSkipped') {
    document.getElementById('hideSkipped').checked = false;
  } else if (act === 'clear') {
    document.getElementById('search').value = '';
    for (const id of ['statusFilter', 'appFilter', 'sourceFilter', 'tierFilter', 'locationFilter']) {
      document.getElementById(id).value = '';
    }
  } else {
    return;
  }
  render();
});

render();
</script>
</body>
</html>
"""


def _file_uri(path: Path) -> str:
    try:
        return path.resolve().as_uri()
    except ValueError:
        return ""


def app_summary(app: dict) -> dict:
    """What the dashboard shows for one tailoring application (src/tailor/store.py row)."""
    status = app.get("status") or "shortlisted"
    label = _APP_LABELS.get(status, status.replace("_", " ").capitalize())
    outcome = app.get("outcome")
    if status == "applied" and outcome and outcome != "applied":
        label = f"Applied: {outcome.replace('_', ' ')}"
    flags = [_FLAG_LABELS.get(f, f.replace("_", " ")) for f in app.get("review_flags") or []]
    if app.get("flagged"):
        flags.append("Gate flag")
    folder = store.folder_path(app.get("folder"))
    final = folder / "final"
    check = folder / "check.md"
    return {
        "status": status,
        "label": label,
        "flags": flags,
        "final_href": _file_uri(final) if app.get("folder") and final.is_dir() else "",
        "check_href": _file_uri(check) if app.get("folder") and check.is_file() else "",
    }


def render_dashboard(conn: sqlite3.Connection, server: bool = False) -> str:
    """The dashboard HTML. With `server`, titles open the details page of the local
    server (scripts/serve.py) instead of only linking to the posting."""
    rows = grouped_jobs(conn)
    apps = store.all_apps(conn)
    for r in rows:
        ids = r.pop("ids")
        app_id = next((i for i in ids if i in apps), None)
        r["app"] = app_summary(apps[app_id]) if app_id is not None else None
        if app_id is not None:
            r["id"] = app_id  # the details page looks the application up by its job id
        status = r["app"]["status"] if r["app"] else None
        r["app_sort"] = _APP_ORDER.index(status) if status in _APP_ORDER else 99
        # A closed posting's application can't be sent, so it isn't pinned as waiting on you.
        # Nor is one you dismissed.
        r["pin"] = (_NEEDS_YOU.index(status) if status in _NEEDS_YOU and not r["closed"]
                    and r.get("status") != "dismissed" else 99)
        # Soonest first when sorted ascending; postings that give no deadline go last.
        r["deadline_sort"] = r.get("deadline") or "9999-12-31"
        r["job_type"] = "internship" if _INTERNSHIP_RE.search(r["title"]) else "fulltime"
        # Skipped / never-scored rows sort below every real score.
        r["score_sort"] = r["score"] if r.get("score") is not None else -9999
        r.pop("description", None)  # the details page fetches it; keeps the page small

    all_sources = sorted({s for r in rows for s in r["sources"]})
    generated_at = escape(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))

    # Plain token replacement rather than str.format() — the template's own
    # CSS/JS is full of literal `{}` braces that .format() would choke on.
    return (
        _TEMPLATE.replace("__GENERATED_AT__", generated_at)
        .replace("__TOTAL__", str(len(rows)))
        .replace("__SOURCES__", str(len(all_sources)))
        .replace("__SERVER__", "true" if server else "false")
        # Job descriptions are untrusted external content — escape "</" so a
        # description containing literal "</script>" can't break out of the tag.
        .replace("__JOBS_JSON__", json.dumps(rows).replace("</", "<\\/"))
    )


def generate_dashboard(conn: sqlite3.Connection, output_path: str | Path) -> Path:
    """Write the static dashboard HTML file. Returns the path written."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_dashboard(conn), encoding="utf-8")
    return output_path

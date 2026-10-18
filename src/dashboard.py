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
from email.utils import parsedate_to_datetime
from html import escape
from pathlib import Path

from src.db import grouped_jobs
from src.search_match import INTERNSHIP_TITLE_RE as _INTERNSHIP_RE
from src.tailor import store
from src.tailor.paths import ROOT

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
_FLAG_LABELS = {"weaker_fit": "Weaker fit", "ats_below_floor": "ATS below 70"}

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
  #statsView { padding: 20px 24px 40px; display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 16px; }
  #statsView[hidden] { display: none; }
  .card { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
  .card h2 { font-size: 14px; margin: 0 0 4px; } .card .sub { color: var(--muted); font-size: 12px; margin-bottom: 12px; }
  .card.wide { grid-column: 1 / -1; }
  .kpis { display: flex; flex-wrap: wrap; gap: 28px; } .kpi b { display: block; font-size: 26px; } .kpi span { color: var(--muted); font-size: 12px; }
  .pie { display: flex; gap: 20px; align-items: center; flex-wrap: wrap; }
  .legend { font-size: 12px; } .legend div { display: flex; gap: 8px; align-items: center; padding: 2px 0; }
  .legend i { width: 10px; height: 10px; border-radius: 2px; display: inline-block; flex: none; }
  .legend .n { color: var(--muted); margin-left: auto; padding-left: 12px; }
  .bars { font-size: 12px; } .bars .r { display: grid; grid-template-columns: 140px 1fr 48px; gap: 8px; align-items: center; padding: 3px 0; }
  .bars .r > span:first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .bars .track { background: var(--bg); border-radius: 3px; height: 12px; } .bars .fill { background: var(--accent); height: 12px; border-radius: 3px; }
  .bars .n { text-align: right; color: var(--muted); }
  table.mini { font-size: 12px; } table.mini th { position: static; cursor: default; }
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>Job Aggregator Dashboard</h1>
  <div class="meta">Generated __GENERATED_AT__ &middot; __TOTAL__ postings across __SOURCES__ sources</div>
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
      <th data-key="years_experience">Years Exp</th>
      <th data-key="sourcesStr">Sources</th>
      <th data-key="posted_sort">Posted</th>
      <th data-key="first_seen">First Seen</th>
    </tr>
  </thead>
  <tbody id="jobsBody"><tr><td class="notice" colspan="11">Loading jobs&hellip;</td></tr></tbody>
</table>
</div>
</div>
<script id="jobs-data" type="application/json">__JOBS_JSON__</script>
<script>
// If anything below throws, say so instead of leaving the "Loading" row up forever.
window.addEventListener('error', e => {
  document.getElementById('jobsBody').innerHTML =
    '<tr><td class="notice error" colspan="11"></td></tr>';
  document.querySelector('#jobsBody td').textContent =
    'The dashboard hit an error and could not show jobs: ' + e.message;
});
const SERVER = __SERVER__;
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
const COLORS = ['#5b8cff', '#3a7d44', '#c9a227', '#b85cd6', '#e57373', '#4fb3bf', '#e08a3c', '#8a94a6', '#7fbf5a', '#d6669e'];
const family = s => s.split(':')[0];
const pct = (n, d) => d ? Math.round(100 * n / d) : 0;

function countBy(items, key) {
  const m = new Map();
  for (const it of items) { const k = key(it); m.set(k, (m.get(k) || 0) + 1); }
  return [...m.entries()].sort((a, b) => b[1] - a[1]);
}

function pieSvg(entries) {
  const total = entries.reduce((a, [, n]) => a + n, 0);
  if (!total) return '';
  if (entries.length === 1) return `<svg width="180" height="180" viewBox="-1 -1 2 2"><circle r="1" fill="${COLORS[0]}"/></svg>`;
  let a0 = -Math.PI / 2, h = '';
  entries.forEach(([, n], i) => {
    const a1 = a0 + 2 * Math.PI * n / total;
    const large = a1 - a0 > Math.PI ? 1 : 0;
    h += `<path d="M0 0 L${Math.cos(a0)} ${Math.sin(a0)} A1 1 0 ${large} 1 ${Math.cos(a1)} ${Math.sin(a1)} Z" fill="${COLORS[i % COLORS.length]}" stroke="#171a21" stroke-width="0.01"/>`;
    a0 = a1;
  });
  return `<svg width="180" height="180" viewBox="-1.02 -1.02 2.04 2.04">${h}</svg>`;
}

function pieCard(title, sub, entries, top = 9) {
  const shown = entries.slice(0, top);
  const rest = entries.slice(top).reduce((a, [, n]) => a + n, 0);
  if (rest) shown.push(['Other', rest]);
  const total = shown.reduce((a, [, n]) => a + n, 0);
  const legend = shown.map(([k, n], i) => `<div><i style="background:${COLORS[i % COLORS.length]}"></i>${escapeHtml(k)}<span class="n">${n} · ${pct(n, total)}%</span></div>`).join('');
  return `<div class="card"><h2>${title}</h2><div class="sub">${sub}</div><div class="pie">${pieSvg(shown)}<div class="legend">${legend}</div></div></div>`;
}

function barsCard(title, sub, entries, wide) {
  const max = Math.max(1, ...entries.map(([, n]) => n));
  const rows = entries.map(([k, n]) => `<div class="r"><span title="${escapeHtml(k)}">${escapeHtml(k)}</span><div class="track"><div class="fill" style="width:${100 * n / max}%"></div></div><span class="n">${n}</span></div>`).join('');
  return `<div class="card${wide ? ' wide' : ''}"><h2>${title}</h2><div class="sub">${sub}</div><div class="bars">${rows || '<span class="n">Nothing yet.</span>'}</div></div>`;
}

function renderStats() {
  const live = jobs.filter(j => j.tier !== 'skip');
  const apps = jobs.filter(j => j.app);
  const kpi = (n, label) => `<div class="kpi"><b>${n}</b><span>${label}</span></div>`;
  const week = new Date(Date.now() - 7 * 864e5).toISOString();
  let h = `<div class="card wide"><div class="kpis">
    ${kpi(jobs.length, 'jobs stored')}${kpi(live.length, 'not skipped')}
    ${kpi(jobs.filter(j => j.tier === 'A').length, 'tier A')}${kpi(jobs.filter(j => j.tier === 'B').length, 'tier B')}
    ${kpi(jobs.filter(j => (j.first_seen || '') >= week).length, 'new in the last 7 days')}
    ${kpi(apps.length, 'tailored applications')}${kpi(jobs.filter(j => j.status === 'applied').length, 'applied')}
  </div></div>`;

  // Each job counted once: under its only source, or "Several sources" when more than one board listed it.
  const bySource = countBy(jobs, j => {
    const fams = [...new Set(j.sources.map(family))];
    return fams.length === 1 ? fams[0] : 'Several sources';
  });
  h += pieCard('Where your jobs come from', 'Each job once; jobs listed by more than one source are grouped', bySource);
  h += pieCard('Where your A and B jobs come from', 'Same, for tier A and B only',
               countBy(jobs.filter(j => j.tier === 'A' || j.tier === 'B'), j => {
                 const fams = [...new Set(j.sources.map(family))];
                 return fams.length === 1 ? fams[0] : 'Several sources';
               }));
  const tierOrder = ['A', 'B', 'C', 'D', 'skip'];
  h += barsCard('Jobs by tier', 'From the score', tierOrder.map(t => [t === 'skip' ? 'Skipped' : 'Tier ' + t, jobs.filter(j => j.tier === t).length]));
  h += barsCard('Jobs by location', 'Vancouver-area, remote, or elsewhere', countBy(jobs, j => j.location_category || 'unknown'));

  // Which source families find good jobs: share of each family's jobs that are tier A or B.
  const fams = countBy(jobs.flatMap(j => [...new Set(j.sources.map(family))].map(f => ({f, j}))), x => x.f);
  const quality = fams.map(([f, n]) => {
    const good = jobs.filter(j => j.sources.some(s => family(s) === f) && (j.tier === 'A' || j.tier === 'B')).length;
    return `<tr><td>${escapeHtml(f)}</td><td>${n}</td><td>${good}</td><td>${pct(good, n)}%</td></tr>`;
  }).join('');
  h += `<div class="card"><h2>Which sources find good jobs</h2><div class="sub">Jobs each source listed, and how many are tier A or B</div>
    <table class="mini"><thead><tr><th>Source</th><th>Jobs</th><th>A or B</th><th>Share</th></tr></thead><tbody>${quality}</tbody></table></div>`;

  const days = [];
  for (let i = 13; i >= 0; i--) {
    const d = new Date(Date.now() - i * 864e5).toISOString().slice(0, 10);
    days.push([d.slice(5), jobs.filter(j => (j.first_seen || '').slice(0, 10) === d).length]);
  }
  h += barsCard('New jobs per day', 'First seen, last 14 days (still stored)', days);
  h += barsCard('Companies with the most jobs', 'Top 12, skipped jobs left out', countBy(live, j => j.company || 'Unknown').slice(0, 12));
  const appOrder = ['needs_fixes', 'ready_for_review', 'approved', 'shortlisted', 'applied'];
  const appLabel = {needs_fixes: 'Needs fixes', ready_for_review: 'Ready for review', approved: 'Approved, not applied', shortlisted: 'Drafting', applied: 'Applied'};
  h += barsCard('Applications', 'Tailored resumes and cover letters by status', appOrder.map(s => [appLabel[s], apps.filter(j => j.app.status === s).length]));
  document.getElementById('statsView').innerHTML = h;
}

function render() {
  const q = document.getElementById('search').value.toLowerCase();
  const status = document.getElementById('statusFilter').value;
  const source = sourceFilterEl.value;
  const locationCat = document.getElementById('locationFilter').value;
  const tier = document.getElementById('tierFilter').value;
  const hideSkipped = document.getElementById('hideSkipped').checked;
  const appStatus = document.getElementById('appFilter').value;

  updateTabs();
  if (activeTab === 'stats') { renderStats(); return; }
  let filtered = jobs.filter(j => {
    if (j.job_type !== activeTab) return false;
    if (status && j.status !== status) return false;
    if (appStatus && !(j.app && (appStatus === 'any' || j.app.status === appStatus))) return false;
    if (source && !j.sources.includes(source)) return false;
    if (locationCat && j.location_category !== locationCat) return false;
    if (tier && j.tier !== tier) return false;
    if (hideSkipped && tier !== 'skip' && j.tier === 'skip') return false;
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
  document.getElementById('count').textContent = `${filtered.length} of ${tabJobs.length} shown`
    + (skippedHidden ? ` \u00b7 ${skippedHidden} skipped hidden` : '');

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
    body.innerHTML = `<tr><td class="notice" colspan="11">${escapeHtml(msg)}${action}</td></tr>`;
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
    const srcBadges = j.sources.map(s => `<span class="badge src">${escapeHtml(s)}</span>`).join('');
    const scoreText = j.tier === 'skip' ? 'skip' : (j.score ?? '');
    return `<tr${j.pin < 99 ? ' class="pinned"' : ''}>
      <td class="score" title="${escapeHtml(j.score_reasons)}"><span class="badge tier-${escapeHtml(j.tier)}">${escapeHtml(j.tier)}</span> ${escapeHtml(String(scoreText))}</td>
      <td>${titleCell}</td>
      <td>${escapeHtml(j.company)}</td>
      <td>${escapeHtml(j.location)}</td>
      <td><span class="badge cat-${escapeHtml(j.location_category)}">${escapeHtml(j.location_category)}</span></td>
      <td><span class="badge status-${escapeHtml(j.status)}">${escapeHtml(j.status)}</span></td>
      <td>${appCell(j.app)}</td>
      <td>${j.years_experience ?? ''}</td>
      <td>${srcBadges}</td>
      <td>${escapeHtml(j.posted_date)}</td>
      <td>${escapeHtml(j.first_seen)}</td>
    </tr>`;
  }).join('');
}

document.querySelectorAll('th[data-key]').forEach(th => {
  th.addEventListener('click', () => {
    const key = th.dataset.key;
    if (sortKey === key) { sortDir *= -1; } else { sortKey = key; sortDir = 1; }
    render();
  });
});

document.getElementById('search').addEventListener('input', render);
document.getElementById('statusFilter').addEventListener('change', render);
document.getElementById('appFilter').addEventListener('change', render);
document.getElementById('locationFilter').addEventListener('change', render);
document.getElementById('tierFilter').addEventListener('change', render);
document.getElementById('hideSkipped').addEventListener('change', render);
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


def _sort_date(posted: str | None, first_seen: str | None) -> str:
    """Normalize the mixed posted_date formats (ISO, 'YYYY-MM-DD', RFC 2822) to
    a UTC ISO string for sorting; jobs with no posted date fall back to when
    they were first seen."""
    for value in (posted, first_seen):
        if not value:
            continue
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                dt = parsedate_to_datetime(value)
            except (TypeError, ValueError):
                continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    return ""


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
    folder = Path(app.get("folder") or "")
    if app.get("folder") and not folder.is_absolute():
        folder = ROOT / folder
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
        r["pin"] = _NEEDS_YOU.index(status) if status in _NEEDS_YOU else 99
        r["posted_sort"] = _sort_date(r.get("posted_date"), r.get("first_seen"))
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

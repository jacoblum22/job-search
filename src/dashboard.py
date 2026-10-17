"""Generate the static HTML dashboard from the jobs DB.

Regenerated fresh on every aggregator run. No server required — just open
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
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; margin: 1px 2px 1px 0; }
  .src { background: var(--panel); border: 1px solid var(--border); color: var(--muted); }
  .status-new { background: var(--new); }
  .status-applied { background: var(--applied); }
  .status-dismissed { background: var(--dismissed); }
  .status-expired { background: var(--dismissed); }
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
</div>
<div class="controls">
  <input type="text" id="search" placeholder="Search title / company / location...">
  <select id="statusFilter">
    <option value="">All statuses</option>
    <option value="new">New</option>
    <option value="applied">Applied</option>
    <option value="dismissed">Dismissed</option>
    <option value="expired">Expired</option>
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
      <th data-key="years_experience">Years Exp</th>
      <th data-key="sourcesStr">Sources</th>
      <th data-key="posted_sort">Posted</th>
      <th data-key="first_seen">First Seen</th>
    </tr>
  </thead>
  <tbody id="jobsBody"><tr><td class="notice" colspan="10">Loading jobs&hellip;</td></tr></tbody>
</table>
</div>
<script id="jobs-data" type="application/json">__JOBS_JSON__</script>
<script>
// If anything below throws, say so instead of leaving the "Loading" row up forever.
window.addEventListener('error', e => {
  document.getElementById('jobsBody').innerHTML =
    '<tr><td class="notice error" colspan="10"></td></tr>';
  document.querySelector('#jobsBody td').textContent =
    'The dashboard hit an error and could not show jobs: ' + e.message;
});
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
let activeTab = location.hash === '#internships' ? 'internship' : 'fulltime';

function updateTabs() {
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
    location.hash = activeTab === 'internship' ? '#internships' : '';
    render();
  });
});

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s ?? '';
  return div.innerHTML;
}

function render() {
  const q = document.getElementById('search').value.toLowerCase();
  const status = document.getElementById('statusFilter').value;
  const source = sourceFilterEl.value;
  const locationCat = document.getElementById('locationFilter').value;
  const tier = document.getElementById('tierFilter').value;
  const hideSkipped = document.getElementById('hideSkipped').checked;

  updateTabs();
  let filtered = jobs.filter(j => {
    if (j.job_type !== activeTab) return false;
    if (status && j.status !== status) return false;
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
    body.innerHTML = `<tr><td class="notice" colspan="10">${escapeHtml(msg)}${action}</td></tr>`;
    return;
  }
  body.innerHTML = filtered.map(j => {
    const link = j.urls.length ? j.urls[0][1] : '';
    const safeLink = /^https?:\/\//i.test(link) ? link : '';
    const titleCell = safeLink
      ? `<a href="${escapeHtml(safeLink)}" target="_blank" rel="noopener noreferrer">${escapeHtml(j.title)}</a>`
      : escapeHtml(j.title);
    const srcBadges = j.sources.map(s => `<span class="badge src">${escapeHtml(s)}</span>`).join('');
    const scoreText = j.tier === 'skip' ? 'skip' : (j.score ?? '');
    return `<tr>
      <td class="score" title="${escapeHtml(j.score_reasons)}"><span class="badge tier-${escapeHtml(j.tier)}">${escapeHtml(j.tier)}</span> ${escapeHtml(String(scoreText))}</td>
      <td>${titleCell}</td>
      <td>${escapeHtml(j.company)}</td>
      <td>${escapeHtml(j.location)}</td>
      <td><span class="badge cat-${escapeHtml(j.location_category)}">${escapeHtml(j.location_category)}</span></td>
      <td><span class="badge status-${escapeHtml(j.status)}">${escapeHtml(j.status)}</span></td>
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
    for (const id of ['statusFilter', 'sourceFilter', 'tierFilter', 'locationFilter']) {
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


def generate_dashboard(conn: sqlite3.Connection, output_path: str | Path) -> Path:
    """Write the static dashboard HTML file. Returns the path written."""
    output_path = Path(output_path)
    rows = grouped_jobs(conn)
    for r in rows:
        r["posted_sort"] = _sort_date(r.get("posted_date"), r.get("first_seen"))
        r["job_type"] = "internship" if _INTERNSHIP_RE.search(r["title"]) else "fulltime"
        # Skipped / never-scored rows sort below every real score.
        r["score_sort"] = r["score"] if r.get("score") is not None else -9999

    all_sources = sorted({s for r in rows for s in r["sources"]})
    generated_at = escape(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))

    # Plain token replacement rather than str.format() — the template's own
    # CSS/JS is full of literal `{}` braces that .format() would choke on.
    html = (
        _TEMPLATE.replace("__GENERATED_AT__", generated_at)
        .replace("__TOTAL__", str(len(rows)))
        .replace("__SOURCES__", str(len(all_sources)))
        # Job descriptions are untrusted external content — escape "</" so a
        # description containing literal "</script>" can't break out of the tag.
        .replace("__JOBS_JSON__", json.dumps(rows).replace("</", "<\\/"))
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path

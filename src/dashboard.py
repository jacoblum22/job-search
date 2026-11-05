"""Generate the static HTML dashboard from the jobs DB.

Regenerated fresh on every aggregator run. No server required — just open
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

_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
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
  .wrap { max-width: 1400px; margin: 0 auto; }
  #count { color: var(--muted); font-size: 13px; margin-left: auto; }
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>Job Aggregator Dashboard</h1>
  <div class="meta">Generated __GENERATED_AT__ &middot; __TOTAL__ postings across __SOURCES__ sources</div>
</header>
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
  <span id="count"></span>
</div>
<table id="jobsTable">
  <thead>
    <tr>
      <th data-key="title">Title</th>
      <th data-key="company">Company</th>
      <th data-key="location">Location</th>
      <th data-key="status">Status</th>
      <th data-key="years_experience">Years Exp</th>
      <th data-key="sourcesStr">Sources</th>
      <th data-key="posted_date">Posted</th>
      <th data-key="first_seen">First Seen</th>
    </tr>
  </thead>
  <tbody id="jobsBody"></tbody>
</table>
</div>
<script id="jobs-data" type="application/json">__JOBS_JSON__</script>
<script>
const rawJobs = JSON.parse(document.getElementById('jobs-data').textContent);
const jobs = rawJobs.map(j => ({...j, sourcesStr: j.sources.join(', ')}));

const allSources = [...new Set(jobs.flatMap(j => j.sources))].sort();
const sourceFilterEl = document.getElementById('sourceFilter');
for (const s of allSources) {
  const opt = document.createElement('option');
  opt.value = s; opt.textContent = s;
  sourceFilterEl.appendChild(opt);
}

let sortKey = 'first_seen', sortDir = -1;

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s ?? '';
  return div.innerHTML;
}

function render() {
  const q = document.getElementById('search').value.toLowerCase();
  const status = document.getElementById('statusFilter').value;
  const source = sourceFilterEl.value;

  let filtered = jobs.filter(j => {
    if (status && j.status !== status) return false;
    if (source && !j.sources.includes(source)) return false;
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

  document.getElementById('count').textContent = `${filtered.length} of ${jobs.length} shown`;

  const body = document.getElementById('jobsBody');
  body.innerHTML = filtered.map(j => {
    const link = j.urls.length ? j.urls[0][1] : '';
    const safeLink = /^https?:\/\//i.test(link) ? link : '';
    const titleCell = safeLink
      ? `<a href="${escapeHtml(safeLink)}" target="_blank" rel="noopener noreferrer">${escapeHtml(j.title)}</a>`
      : escapeHtml(j.title);
    const srcBadges = j.sources.map(s => `<span class="badge src">${escapeHtml(s)}</span>`).join('');
    return `<tr>
      <td>${titleCell}</td>
      <td>${escapeHtml(j.company)}</td>
      <td>${escapeHtml(j.location)}</td>
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
sourceFilterEl.addEventListener('change', render);

render();
</script>
</body>
</html>
"""


def generate_dashboard(conn: sqlite3.Connection, output_path: str | Path) -> Path:
    """Write the static dashboard HTML file. Returns the path written."""
    output_path = Path(output_path)
    rows = grouped_jobs(conn)

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

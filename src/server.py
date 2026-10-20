"""Local dashboard server: the dashboard plus a details page per job where you can
tick check.md, approve, and record what happened, without the command line.

Run with `uv run python scripts/serve.py`. It listens on 127.0.0.1 only. Requests
that change anything must be JSON from the page itself (same Origin and Host), so
another website open in the browser can't press its buttons.

`DashboardApp.handle` does the work and returns (status, content type, body), so
tests call it directly without a socket.
"""

from __future__ import annotations

import json
import mimetypes
import re
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.dashboard import app_summary, generate_dashboard, render_dashboard
from src.db import JOB_STATUSES, connect, set_job_status
from src.posting_status import closed_reason, seen_date
from src.tailor import TailorError, review, store
from src.tailor.packet import OUTCOMES, approve, record_outcome

Response = tuple[int, str, bytes]
_JOB = re.compile(r"^/(?:api/)?job/(\d+)(/.*)?$")
# Files from an application's final/ folder the details page may link to.
_SERVABLE = {".pdf", ".docx", ".md", ".json", ".yaml"}


class DashboardApp:
    def __init__(self, cfg: dict[str, Any], db_path: Path, dashboard_path: Path | None = None,
                 port: int = 8765) -> None:
        self.cfg = cfg
        self.db_path = Path(db_path)
        self.dashboard_path = dashboard_path
        self.origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    # --- plumbing -------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        conn = connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _refresh_file(self, conn: sqlite3.Connection) -> None:
        """Keep dashboard.html (the file you can open without the server) current too."""
        if self.dashboard_path:
            generate_dashboard(conn, self.dashboard_path)

    @staticmethod
    def _json(data: Any, status: int = 200) -> Response:
        return status, "application/json", json.dumps(data).encode()

    @staticmethod
    def _error(message: str, status: int = 400) -> Response:
        return status, "application/json", json.dumps({"error": message}).encode()

    def handle(self, method: str, path: str, headers: dict[str, str], body: bytes = b"") -> Response:
        headers = {k.lower(): v for k, v in headers.items()}
        if headers.get("host") not in self.hosts:
            return self._error("unknown host", 403)
        path = path.split("?", 1)[0]
        try:
            if method == "GET":
                return self._get(path)
            if method == "POST":
                if headers.get("origin") not in self.origins:
                    return self._error("cross-site request refused", 403)
                if not headers.get("content-type", "").startswith("application/json"):
                    return self._error("send JSON", 415)
                try:
                    data = json.loads(body or b"{}")
                except json.JSONDecodeError:
                    return self._error("bad JSON")
                return self._post(path, data if isinstance(data, dict) else {})
            return self._error("method not allowed", 405)
        except TailorError as e:
            return self._error(str(e), 409)

    # --- reads ----------------------------------------------------------

    def _get(self, path: str) -> Response:
        if path in ("/", "/index.html"):
            conn = self._conn()
            try:
                return 200, "text/html; charset=utf-8", render_dashboard(conn, server=True).encode()
            finally:
                conn.close()
        m = _JOB.match(path)
        if not m:
            return self._error("not found", 404)
        job_id, rest = int(m[1]), m[2] or ""
        if path.startswith("/job/") and rest == "":
            return 200, "text/html; charset=utf-8", DETAILS_PAGE.encode()
        if path.startswith("/api/job/") and rest == "":
            return self._details(job_id)
        if path.startswith("/job/") and rest.startswith("/file/"):
            return self._file(job_id, rest.removeprefix("/file/"))
        return self._error("not found", 404)

    def _app_for(self, conn: sqlite3.Connection, job_id: int) -> tuple[sqlite3.Row | None, dict | None]:
        job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if job is None:
            return None, None
        apps = store.all_apps(conn)
        ids = [r[0] for r in conn.execute("SELECT id FROM jobs WHERE dedup_group_id = ?",
                                          (job["dedup_group_id"],))] or [job_id]
        app = apps.get(job_id) or next((apps[i] for i in ids if i in apps), None)
        return job, app

    def _folder(self, app: dict) -> Path:
        from src.tailor.paths import ROOT

        p = Path(app["folder"])
        return p if p.is_absolute() else ROOT / p

    def _details(self, job_id: int) -> Response:
        conn = self._conn()
        try:
            job, app = self._app_for(conn, job_id)
            group = conn.execute("SELECT description, first_seen FROM jobs WHERE dedup_group_id = "
                                 "(SELECT dedup_group_id FROM jobs WHERE id = ?)", (job_id,)).fetchall()
        finally:
            conn.close()
        if job is None:
            return self._error("no such job", 404)
        closed = next((c for d, seen in group if (c := closed_reason(d or "", seen=seen_date(seen)))), None)
        out: dict[str, Any] = {
            "job": {k: job[k] for k in ("id", "title", "company", "location", "url", "status", "tier", "score",
                                        "score_reasons", "posted_date", "first_seen", "description", "source")},
            "closed": closed,
            "job_statuses": list(JOB_STATUSES),
            "outcomes": list(OUTCOMES),
            "app": None,
        }
        if app:
            folder = self._folder(app)
            check = folder / "check.md"
            final = folder / "final"
            text = check.read_text(encoding="utf-8") if check.exists() else None
            out["app"] = {
                **app_summary(app),
                "job_id": app["job_id"],
                "outcome": app.get("outcome"),
                "folder": str(folder),
                "check": review.parse(text) if text is not None else None,
                "open_items": review.open_items(text) if text is not None else None,
                "files": sorted(p.name for p in final.iterdir() if p.is_file() and p.suffix.lower() in _SERVABLE
                                and not p.name.startswith("~$")) if final.is_dir() else [],
            }
        return self._json(out)

    def _file(self, job_id: int, name: str) -> Response:
        from urllib.parse import unquote

        name = unquote(name)
        conn = self._conn()
        try:
            _, app = self._app_for(conn, job_id)
        finally:
            conn.close()
        if not app:
            return self._error("no application for this job", 404)
        final = self._folder(app) / "final"
        # Only a plain file name that is actually in final/: no paths, no "..".
        names = {p.name for p in final.iterdir()} if final.is_dir() else set()
        if "/" in name or "\\" in name or name not in names:
            return self._error("not found", 404)
        path = final / name
        if path.suffix.lower() not in _SERVABLE or not path.is_file():
            return self._error("not found", 404)
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix.lower() in {".md", ".yaml", ".json"}:
            ctype = "text/plain; charset=utf-8"
        return 200, ctype, path.read_bytes()

    # --- changes --------------------------------------------------------

    def _post(self, path: str, data: dict[str, Any]) -> Response:
        m = _JOB.match(path)
        if not m or not path.startswith("/api/job/"):
            return self._error("not found", 404)
        job_id, action = int(m[1]), (m[2] or "").strip("/")
        actions: dict[str, Callable[[sqlite3.Connection, int, dict | None, dict], Any]] = {
            "check": self._tick, "approve": self._approve, "outcome": self._outcome, "status": self._status,
        }
        if action not in actions:
            return self._error("not found", 404)
        conn = self._conn()
        try:
            job, app = self._app_for(conn, job_id)
            if job is None:
                return self._error("no such job", 404)
            result = actions[action](conn, job_id, app, data)
            self._refresh_file(conn)
        finally:
            conn.close()
        return self._json({"ok": True, "result": result})

    def _need_app(self, app: dict | None) -> dict:
        if not app:
            raise TailorError("this job has no tailored application")
        return app

    def _tick(self, conn, job_id, app, data) -> Any:
        app = self._need_app(app)
        try:
            line, raw, option, checked = int(data["line"]), str(data["raw"]), str(data["option"]), bool(data["checked"])
        except (KeyError, TypeError, ValueError):
            raise TailorError("send line, raw, option and checked") from None
        blocks = review.tick(self._folder(app), line, raw, option, checked)
        return {"check": blocks}

    def _approve(self, conn, job_id, app, data) -> Any:
        app = self._need_app(app)
        return approve(self._folder(app), self.cfg)

    def _outcome(self, conn, job_id, app, data) -> Any:
        app = self._need_app(app)
        outcome = str(data.get("outcome", ""))
        if outcome not in OUTCOMES:
            raise TailorError(f"outcome must be one of {', '.join(OUTCOMES)}")
        return record_outcome(self._folder(app), self.cfg, outcome)

    def _status(self, conn, job_id, app, data) -> Any:
        status = str(data.get("status", ""))
        if status not in JOB_STATUSES:
            raise TailorError(f"status must be one of {', '.join(JOB_STATUSES)}")
        if app and status == "applied":
            # Keeps the application's record (and its outcome history) in step.
            return record_outcome(self._folder(app), self.cfg, "applied")
        return {"changed": set_job_status(conn, job_id, status)}


DETAILS_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Job details</title>
<style>
  :root { --bg: #0f1115; --panel: #171a21; --border: #2a2e38; --text: #e6e8ec; --muted: #9aa1ad;
          --accent: #5b8cff; --good: #3a7d44; --warn: #c9a227; --bad: #e57373; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: -apple-system, Segoe UI, sans-serif; background: var(--bg); color: var(--text); }
  .wrap { max-width: 960px; margin: 0 auto; padding: 20px 16px 60px; }
  a { color: var(--accent); text-decoration: none; } a:hover { text-decoration: underline; }
  h1 { font-size: 22px; margin: 8px 0 4px; } h2 { font-size: 16px; margin: 28px 0 8px; }
  h3 { font-size: 14px; margin: 18px 0 6px; color: var(--muted); }
  .meta { color: var(--muted); font-size: 13px; }
  .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; margin-top: 12px; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; margin: 0 4px 4px 0; background: var(--border); }
  .badge.flag { background: none; border: 1px solid var(--warn); color: #e0c060; }
  button { background: var(--panel); border: 1px solid var(--border); color: var(--text); padding: 6px 12px;
           border-radius: 6px; cursor: pointer; font-size: 13px; margin: 4px 6px 4px 0; }
  button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
  button:disabled { opacity: .5; cursor: default; }
  .item { display: flex; gap: 10px; align-items: flex-start; padding: 6px 0; border-bottom: 1px solid var(--border); font-size: 13px; }
  .item:last-child { border-bottom: none; }
  .item .boxes { display: flex; flex-direction: column; gap: 6px; width: 150px; flex: none; padding-top: 2px; }
  button.pick { margin: 0; width: 100%; font-size: 12px; padding: 5px 8px; border-radius: 6px; background: none;
                text-align: center; white-space: nowrap; }
  button.pick.review { border-color: #6b7280; color: #c4cbd8; }
  button.pick.review.on { background: var(--accent); border-color: var(--accent); color: #fff; }
  button.pick.good { border-color: #3a7d44; color: #8fd19e; }
  button.pick.good.on { background: #3a7d44; color: #fff; }
  button.pick.bad { border-color: #b85454; color: #f2a5a5; }
  button.pick.bad.on { background: #b85454; color: #fff; }
  button.pick.warn { border-color: #c9a227; color: #e0c060; }
  button.pick.warn.on { background: #c9a227; color: #1a1a1a; }
  button.pick.on { cursor: default; font-weight: 600; } button.pick.review.on { cursor: pointer; }
  .item .details { color: var(--muted); margin-top: 2px; }
  .item.open .text { color: var(--text); font-weight: 600; }
  .line { font-size: 13px; padding: 2px 0; } .line.bullet::before { content: "• "; color: var(--muted); }
  .line.sub { margin-left: 18px; color: var(--muted); }
  pre { white-space: pre-wrap; font-family: inherit; font-size: 13px; line-height: 1.5; margin: 0; }
  #msg { position: sticky; top: 0; padding: 8px 12px; border-radius: 6px; display: none; margin-bottom: 8px; font-size: 13px; }
  #msg.err { display: block; background: #3a1d1d; color: var(--bad); }
  #msg.ok { display: block; background: #1d3a24; color: #8fd19e; }
  .row { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; }
  details summary { cursor: pointer; color: var(--muted); font-size: 13px; }
  .note { background: #1b2233; border-left: 3px solid var(--accent); color: #c4cbd8; font-size: 13px;
          line-height: 1.5; padding: 8px 12px; border-radius: 4px; margin: 4px 0 10px; }
  .item .text { line-height: 1.45; }
  .item .details { line-height: 1.45; margin-top: 4px; }
  .key { color: var(--text); font-weight: 600; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0 8px; }
  .chip { background: var(--border); border-radius: 12px; padding: 2px 10px; font-size: 12px; color: var(--text); }
  .chip.none { background: none; border: 1px dashed var(--border); color: var(--muted); }
  .diff { font-size: 13px; line-height: 1.5; margin: 2px 0 10px 18px; color: var(--muted); }
  .diff > div { padding: 2px 0; }
  .diff .key { display: inline-block; width: 52px; color: var(--muted); font-weight: 600; }
  del { background: #4a2326; color: #f2b8b8; text-decoration: line-through; border-radius: 3px; padding: 0 2px; }
  ins { background: #1f4229; color: #b6e8c0; text-decoration: none; border-radius: 3px; padding: 0 2px; }
  code { background: var(--border); padding: 0 4px; border-radius: 3px; font-size: 12px; }
  .posting { font-size: 14px; line-height: 1.55; }
  .posting h4 { margin: 16px 0 6px; font-size: 14px; } .posting h4:first-child { margin-top: 0; }
  .posting p { margin: 6px 0; } .posting ul, .posting ol { margin: 6px 0; padding-left: 22px; }
  .posting li { margin: 2px 0; }
</style>
</head>
<body>
<div class="wrap">
  <a href="/">&larr; Dashboard</a>
  <div id="msg"></div>
  <div id="root"><p class="meta">Loading&hellip;</p></div>
</div>
<script>
const jobId = location.pathname.split('/')[2];
const root = document.getElementById('root');
const msgEl = document.getElementById('msg');
let data = null;

function esc(s) { const d = document.createElement('div'); d.textContent = s ?? ''; return d.innerHTML; }
function say(text, ok) { msgEl.textContent = text; msgEl.className = ok ? 'ok' : 'err'; }

async function post(action, body) {
  const r = await fetch(`/api/job/${jobId}/${action}`, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})});
  const j = await r.json().catch(() => ({error: 'The server sent something unreadable.'}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j.result;
}

async function load() {
  const r = await fetch(`/api/job/${jobId}`);
  if (!r.ok) { root.innerHTML = '<p class="meta">This job is not in the database any more.</p>'; return; }
  data = await r.json();
  render();
}

// Inline markdown on already-escaped text: **bold**, *italic*, `code`, and http(s) links.
function inline(s) {
  return esc(s)
    .replace(/\\([\\`*_{}\[\]()#+\-.!|])/g, (m, c) => `&#${c.charCodeAt(0)};`)  // \* is a literal *
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*\w])\*([^*\s][^*]*?)\*(?=[^*\w]|$)/g, '$1<em>$2</em>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)"]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}

// Postings arrive as plain text, markdown, or HTML, often with entities like &amp;.
// HTML is read with DOMParser (an inert document: nothing in it runs) and turned into lines.
function postingText(raw) {
  raw = raw || '';
  const doc = new DOMParser().parseFromString(raw, 'text/html');
  if (!/<(p|div|br|li|ul|ol|h[1-6]|strong|b)\b/i.test(raw)) return doc.documentElement.textContent;
  doc.querySelectorAll('li').forEach(li => li.prepend('* '));
  doc.querySelectorAll('h1,h2,h3,h4,h5,h6').forEach(h => { h.prepend('### '); });
  doc.querySelectorAll('strong,b').forEach(b => { b.prepend('**'); b.append('**'); });
  doc.querySelectorAll('br').forEach(br => br.replaceWith('\n'));
  doc.querySelectorAll('p,div,li,ul,ol,h1,h2,h3,h4,h5,h6,tr').forEach(el => el.append('\n'));
  return doc.body.textContent;
}

function markdown(raw) {
  const lines = postingText(raw).replace(/\r/g, '').split('\n');
  let h = '', list = null, para = [];
  const flush = () => {
    if (para.length) { h += `<p>${inline(para.join(' '))}</p>`; para = []; }
    if (list) { h += `</${list}>`; list = null; }
  };
  for (const line of lines) {
    const t = line.trim();
    if (!t) { flush(); continue; }
    let m;
    if ((m = t.match(/^#{1,6}\s+(.*)$/))) { flush(); h += `<h4>${inline(m[1])}</h4>`; continue; }
    if ((m = t.match(/^\*\*([^*]+)\*\*:?$/))) { flush(); h += `<h4>${inline(m[1])}</h4>`; continue; }
    const bullet = t.match(/^(?:[*\-•·▪]|\d+[.)])\s+(.*)$/);
    if (bullet) {
      if (para.length) { h += `<p>${inline(para.join(' '))}</p>`; para = []; }
      const kind = /^\d/.test(t) ? 'ol' : 'ul';
      if (list !== kind) { if (list) h += `</${list}>`; h += `<${kind}>`; list = kind; }
      h += `<li>${inline(bullet[1])}</li>`;
      continue;
    }
    if (list) { h += `</${list}>`; list = null; }
    para.push(t);
  }
  flush();
  return h || '<p class="meta">No description stored.</p>';
}

// Word-level difference between two versions of a resume line.
function wordDiff(a, b) {
  const x = a.split(/\s+/), y = b.split(/\s+/);
  const n = x.length, m = y.length;
  const L = Array.from({length: n + 1}, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
    L[i][j] = x[i] === y[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  // Runs of changed words become one highlight, so a reworded phrase reads as one change.
  const before = [], after = [];
  const add = (out, tag, word) => {
    const last = out[out.length - 1];
    if (tag && last && last.tag === tag) last.words.push(word); else out.push({tag, words: [word]});
  };
  let i = 0, j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && x[i] === y[j]) { add(before, '', x[i]); add(after, '', y[j]); i++; j++; }
    else if (j < m && (i >= n || L[i][j + 1] >= L[i + 1][j])) { add(after, 'ins', y[j]); j++; }
    else { add(before, 'del', x[i]); i++; }
  }
  const html = out => out.map(r => r.tag ? `<${r.tag}>${esc(r.words.join(' '))}</${r.tag}>` : esc(r.words.join(' '))).join(' ');
  return [html(before), html(after)];
}

function detailsHtml(details) {
  let h = '', chips = [];
  const flush = () => { if (chips.length) { h += `<div class="chips">${chips.join('')}</div>`; chips = []; } };
  for (const d of details) {
    const text = typeof d === 'string' ? d : d.text;
    if (d.level === 2) { chips.push(`<span class="chip${text === 'None' ? ' none' : ''}">${inline(text)}</span>`); continue; }
    flush();
    const m = text.match(/^(The (?:passage|line|bullet|summary|sentence|posting says)|Why|Why it matters|Judge|Checker's note|Jev was asked):\s*(.*)$/);
    h += m ? `<div class="details"><span class="key">${esc(m[1])}:</span> ${inline(m[2])}</div>`
           : `<div class="details">${inline(text)}</div>`;
  }
  flush();
  return h;
}

// Button wording per kind of check.md line: [unselected, selected, colour] for each box.
const BUTTONS = {
  reviewed: [['In review', 'Reviewed', 'review']],
  keep_remove: [['Keep', 'Keep', 'good'], ['Remove', 'Remove', 'bad']],
  drop: [['Correctly set aside', 'Correctly set aside', 'good'], ['Shows the skill', 'Shows the skill', 'warn']],
  confirm: [["Doesn't show it", "Doesn't show it", 'bad'], ['This shows it', 'This shows it', 'good']],
  undo: [['Undo', 'Undo', 'warn']],
};
const PAIRS = new Set(['keep_remove', 'drop', 'confirm']);

function checkHtml(blocks) {
  let h = '';
  for (let k = 0; k < blocks.length; k++) {
    const b = blocks[k];
    if (b.type === 'heading') {
      if (b.level > 1) h += `<h3>${esc(b.text)}</h3>`;
    } else if (b.type === 'note') {
      h += `<div class="note">${inline(b.text)}</div>`;
    } else if (b.type === 'text') {
      const next = blocks[k + 1];
      if (b.indent && /^Before: /.test(b.text) && next && next.type === 'text' && /^After: /.test(next.text)) {
        const [before, after] = wordDiff(b.text.slice(8), next.text.slice(7));
        h += `<div class="diff"><div><span class="key">Before</span> ${before}</div><div><span class="key">After</span> ${after}</div></div>`;
        k++;
      } else if (b.indent && /^(Before|After): /.test(b.text)) {
        const [key, rest] = [b.text.slice(0, b.text.indexOf(':')), b.text.slice(b.text.indexOf(':') + 2)];
        h += `<div class="diff"><div><span class="key">${esc(key)}</span> ${inline(rest)}</div></div>`;
      } else {
        h += `<div class="line${b.bullet ? ' bullet' : ''}${b.indent ? ' sub' : ''}">${inline(b.text)}</div>`;
      }
    } else {
      const open = b.kind !== 'undo' && !b.options.some(o => o.checked);
      const boxes = b.options.map((o, i) => {
        const [off, on, tone] = (BUTTONS[b.kind] || [])[i] || [o.name, o.name, 'neutral'];
        return `<button class="pick ${tone}${o.checked ? ' on' : ''}" data-line="${b.line}" data-opt="${esc(o.name)}"
          data-checked="${o.checked}" title="${esc(o.name)}">${o.checked ? '✓ ' : ''}${esc(o.checked ? on : off)}</button>`;
      }).join('');
      h += `<div class="item${open ? ' open' : ''}"><div class="boxes">${boxes}</div>
        <div><div class="text">${inline(b.text)}</div>${detailsHtml(b.details)}</div></div>`;
    }
  }
  return h;
}

function render() {
  const {job, app, closed} = data;
  document.title = `${job.title} · ${job.company}`;
  let h = `<h1>${esc(job.title)}</h1>
    <div class="meta">${esc(job.company)} · ${esc(job.location)} · Tier ${esc(job.tier)} ${job.score ?? ''}
    · posted ${esc(job.posted_date || job.first_seen || '')}</div>
    ${closed ? `<div class="meta" style="color:#e07070;margin-top:6px">${esc(closed)}: this posting no longer takes applications.</div>` : ''}
    <div class="row" style="margin-top:8px">`;
  if (/^https?:\/\//i.test(job.url || '')) h += `<a href="${esc(job.url)}" target="_blank" rel="noopener noreferrer">Open the posting</a>`;
  h += `</div>`;

  if (app) {
    const flags = app.flags.map(f => `<span class="badge flag">${esc(f)}</span>`).join('');
    const files = app.files.map(f => `<a href="/job/${jobId}/file/${encodeURIComponent(f)}" target="_blank">${esc(f)}</a>`).join('<br>');
    h += `<h2>Application</h2><div class="panel">
      <div class="row"><span class="badge">${esc(app.label)}</span>${flags}</div>
      <div class="meta" style="margin-top:6px">Folder: ${esc(app.folder)}</div>
      ${files ? `<div style="margin-top:10px">${files}</div>` : '<div class="meta">No rendered files yet.</div>'}
      <div class="row" style="margin-top:12px">`;
    if (app.status === 'needs_fixes') {
      h += `<span class="meta">The checker found critical problems, so this can't be approved yet. Run another repair round, then the packet step again.</span>`;
    }
    if (app.status === 'ready_for_review') {
      const left = app.open_items || 0;
      h += `<button class="primary" data-act="approve" ${left ? 'disabled' : ''}>Approve</button>
        <span class="meta">${left ? `${left} item${left === 1 ? '' : 's'} below still need${left === 1 ? 's' : ''} a decision` : 'Every item is decided.'}</span>`;
    }
    if (app.status === 'approved') h += `<button class="primary" data-act="outcome" data-val="applied">I applied</button>`;
    if (app.status === 'applied') {
      h += `<span class="meta">Record what happened:</span>` + data.outcomes.filter(o => o !== 'applied')
        .map(o => `<button data-act="outcome" data-val="${o}" ${app.outcome === o ? 'disabled' : ''}>${esc(o.replace('_', ' '))}</button>`).join('');
    }
    h += `</div></div>`;
    if (app.check) h += `<h2>Checklist</h2><div class="panel" id="check">${checkHtml(app.check)}</div>`;
  } else {
    h += `<h2>Status</h2><div class="panel"><div class="row"><span class="badge">${esc(job.status)}</span>`
      + data.job_statuses.filter(s => s !== job.status && s !== 'expired')
        .map(s => `<button data-act="status" data-val="${s}">Mark ${esc(s)}</button>`).join('')
      + `</div><div class="meta" style="margin-top:6px">No tailored resume or cover letter yet.</div></div>`;
  }
  if (job.score_reasons) h += `<details style="margin-top:20px"><summary>Why it scored ${job.score ?? ''}</summary><pre class="meta">${esc(job.score_reasons)}</pre></details>`;
  h += `<h2>Posting</h2><div class="panel posting">${markdown(job.description)}</div>`;
  root.innerHTML = h;
}

// Reviewed toggles; in a pair, the picked button stays picked until the other one is pressed.
root.addEventListener('click', async e => {
  const btn = e.target.closest('button.pick');
  if (!btn) return;
  const line = Number(btn.dataset.line);
  const block = data.app.check.find(b => b.line === line);
  const picked = btn.dataset.checked === 'true';
  if (picked && PAIRS.has(block.kind)) return;
  try {
    await post('check', {line, raw: block.raw, option: btn.dataset.opt, checked: !picked});
    msgEl.className = '';
    await load();
  } catch (err) { say(err.message); await load(); }
});

root.addEventListener('click', async e => {
  const act = e.target.dataset && e.target.dataset.act;
  if (!act) return;
  e.target.disabled = true;
  try {
    if (act === 'approve') { await post('approve'); say('Approved. Apply with the files above, then press "I applied".', true); }
    if (act === 'outcome') { await post('outcome', {outcome: e.target.dataset.val}); say('Saved.', true); }
    if (act === 'status') { await post('status', {status: e.target.dataset.val}); say('Saved.', true); }
  } catch (err) { say(err.message); }
  await load();
});

load();
</script>
</body>
</html>
"""

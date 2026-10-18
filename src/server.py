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
        finally:
            conn.close()
        if job is None:
            return self._error("no such job", 404)
        out: dict[str, Any] = {
            "job": {k: job[k] for k in ("id", "title", "company", "location", "url", "status", "tier", "score",
                                        "score_reasons", "posted_date", "first_seen", "description", "source")},
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
  .item .boxes { display: flex; gap: 10px; white-space: nowrap; }
  .item label { cursor: pointer; color: var(--muted); } .item label.on { color: var(--text); }
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

function checkHtml(blocks) {
  let h = '';
  for (const b of blocks) {
    if (b.type === 'heading') {
      if (b.level > 1) h += `<h3>${esc(b.text)}</h3>`;
    } else if (b.type === 'text') {
      h += `<div class="line${b.bullet ? ' bullet' : ''}${b.indent ? ' sub' : ''}">${esc(b.text)}</div>`;
    } else {
      const open = b.kind !== 'undo' && !b.options.some(o => o.checked);
      const boxes = b.options.map((o, i) => `<label class="${o.checked ? 'on' : ''}"><input type="checkbox"
        data-line="${b.line}" data-opt="${esc(o.name)}" ${o.checked ? 'checked' : ''}> ${esc(o.name)}</label>`).join('');
      const details = b.details.map(d => `<div class="details">${esc(d)}</div>`).join('');
      h += `<div class="item${open ? ' open' : ''}"><div class="boxes">${boxes}</div>
        <div><div class="text">${esc(b.text)}</div>${details}</div></div>`;
    }
  }
  return h;
}

function render() {
  const {job, app} = data;
  document.title = `${job.title} · ${job.company}`;
  let h = `<h1>${esc(job.title)}</h1>
    <div class="meta">${esc(job.company)} · ${esc(job.location)} · Tier ${esc(job.tier)} ${job.score ?? ''}
    · posted ${esc(job.posted_date || job.first_seen || '')}</div>
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
        <span class="meta">${left ? `${left} box${left === 1 ? '' : 'es'} below still need a decision` : 'Every box is decided.'}</span>`;
    }
    if (app.status === 'approved') h += `<button class="primary" data-act="outcome" data-val="applied">I applied</button>`;
    if (app.status === 'applied') {
      h += `<span class="meta">Record what happened:</span>` + data.outcomes.filter(o => o !== 'applied')
        .map(o => `<button data-act="outcome" data-val="${o}" ${app.outcome === o ? 'disabled' : ''}>${esc(o.replace('_', ' '))}</button>`).join('');
    }
    h += `</div></div>`;
    if (app.check) h += `<h2>Checklist</h2><div class="meta">Tick Reviewed once you've read a flag. For each remaining issue, Keep means it's fine as it is and Remove means you'll change it before applying. Undo puts a rejected evidence match back.</div><div class="panel" id="check">${checkHtml(app.check)}</div>`;
  } else {
    h += `<h2>Status</h2><div class="panel"><div class="row"><span class="badge">${esc(job.status)}</span>`
      + data.job_statuses.filter(s => s !== job.status && s !== 'expired')
        .map(s => `<button data-act="status" data-val="${s}">Mark ${esc(s)}</button>`).join('')
      + `</div><div class="meta" style="margin-top:6px">No tailored resume or cover letter yet.</div></div>`;
  }
  if (job.score_reasons) h += `<details style="margin-top:20px"><summary>Why it scored ${job.score ?? ''}</summary><pre class="meta">${esc(job.score_reasons)}</pre></details>`;
  h += `<h2>Posting</h2><div class="panel"><pre>${esc(job.description || 'No description stored.')}</pre></div>`;
  root.innerHTML = h;
}

root.addEventListener('change', async e => {
  const box = e.target;
  if (!box.dataset || box.dataset.line === undefined) return;
  const line = Number(box.dataset.line);
  const block = data.app.check.find(b => b.line === line);
  try {
    const res = await post('check', {line, raw: block.raw, option: box.dataset.opt, checked: box.checked});
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

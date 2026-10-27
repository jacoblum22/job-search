"""Run the dashboard as a local web app: details page per job, tick check.md,
approve, and record outcomes from the browser.

    uv run python scripts/serve.py            # http://127.0.0.1:8765, opens the browser
    uv run python scripts/serve.py --port 9000 --no-browser
    uv run python scripts/serve.py --no-browser --allow-host desktop.tailnet.ts.net

Listens on 127.0.0.1 only; stop it with Ctrl+C. To open it from your other devices,
run `tailscale serve --bg 8765` on this PC and pass the address it prints as
--allow-host (requests naming any other host are refused).

Run it with .venv/Scripts/pythonw.exe to keep it out of sight (no console window);
its output then goes to logs/dashboard.log.

dashboard.html is rewritten after
every change, so the plain file stays current too.
"""

from __future__ import annotations

import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import click

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.server import DashboardApp
from src.tailor.paths import load_config, resolve


def make_handler(app: DashboardApp) -> type[BaseHTTPRequestHandler]:
    # One request at a time: check.md and jobs.db edits never interleave.
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def _send(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            with lock:
                status, ctype, data = app.handle(method, self.path, dict(self.headers.items()), body)
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            # Pages may stay in the browser's back/forward cache (Back is instant); data never is cached.
            self.send_header("Cache-Control", "no-cache" if ctype.startswith("text/html") else "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            self._send("GET")

        def do_POST(self) -> None:
            self._send("POST")

        def log_message(self, fmt: str, *args) -> None:
            if args and str(args[1])[:1] in "45":  # only log failures
                super().log_message(fmt, *args)

    return Handler


@click.command()
@click.option("--port", default=8765, show_default=True)
@click.option("--no-browser", is_flag=True, help="Don't open the dashboard in a browser")
@click.option("--allow-host", "allow_hosts", multiple=True, metavar="HOST",
              help="Also accept this host name, e.g. the address `tailscale serve` gives "
                   "(desktop.tailnet.ts.net). Repeatable.")
def main(port: int, no_browser: bool, allow_hosts: tuple[str, ...]) -> None:
    if sys.stdout is None or sys.stderr is None:
        # Run windowless (pythonw.exe, as the JobSearch-Dashboard task does): there is no
        # console, so output and request errors go to logs/dashboard.log instead.
        log_dir = PROJECT_ROOT / "logs"
        log_dir.mkdir(exist_ok=True)
        log = open(log_dir / "dashboard.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log
    cfg = load_config()
    app = DashboardApp(cfg, resolve(cfg, "db"), PROJECT_ROOT / "dashboard.html", port=port,
                       extra_hosts=allow_hosts)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    url = f"http://127.0.0.1:{port}/"
    click.echo(f"Dashboard at {url} (Ctrl+C to stop)")
    if not no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

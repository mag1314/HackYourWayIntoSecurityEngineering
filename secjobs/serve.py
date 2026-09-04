"""Local HTTP bridge for the browser userscript.

    secjobs serve            ->  http://127.0.0.1:8765

The userscript (userscript/secjobs-lever.user.js) running in YOUR normal
Chrome asks this server for the tailored resume, cover letter and answers for
the posting currently open, fills the form in place, and reports back when
you submit. No automation framework touches the browser, so hCaptcha sees an
ordinary session.

Binds to localhost only. Nothing is reachable from the network.
"""
import base64, json, re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from . import config
from .config import OUTPUT_DIR
from .tracker import Tracker

HOST, PORT = "127.0.0.1", 8765
_ID = re.compile(r"jobs\.lever\.co/([^/]+)/([0-9a-f-]{36})")


def _find_output(company: str, posting_id: str):
    d = OUTPUT_DIR / company
    if not d.exists():
        # slug case may differ (AMIRI vs amiri)
        for c in OUTPUT_DIR.iterdir():
            if c.name.lower() == company.lower():
                d = c; break
    hits = list(d.glob(f"*-{posting_id[:8]}")) if d.exists() else []
    return hits[0] if hits else None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quieter
        if "/job" in fmt % args or "/applied" in fmt % args:
            print("  " + (fmt % args))

    def _send(self, code: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "https://jobs.lever.co")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/ping":
            return self._send(200, {"ok": True})
        if u.path != "/job":
            return self._send(404, {"error": "unknown"})
        url = parse_qs(u.query).get("url", [""])[0]
        m = _ID.search(url)
        if not m:
            return self._send(400, {"error": "not a Lever apply URL"})
        company, pid = m.group(1), m.group(2)

        tr = Tracker()
        row = tr.get(pid)
        cand = config.candidate()
        out = _find_output(company, pid)
        body = {
            "posting_id": pid, "company": company,
            "status": row["status"] if row else None,
            "title": row["title"] if row else None,
            "known": row is not None,
            "generated": out is not None and (out / "resume.pdf").exists(),
            "candidate": {k: cand.get(k, "") for k in ("full_name", "email", "phone", "location", "linkedin")},
            "eeo": cand.get("eeo", {}) or {},
            "answers": cand.get("answers", []) or [],
        }
        if body["generated"]:
            body["cover_letter"] = (out / "cover_letter.txt").read_text(encoding="utf-8")
            body["resume_name"] = re.sub(r"[^A-Za-z0-9]+", "_", cand.get("full_name", "Resume")).strip("_") + "_Resume.pdf"
            body["resume_b64"] = base64.b64encode((out / "resume.pdf").read_bytes()).decode()
            body["flags"] = [l for l in (out / "REVIEW_FLAGS.txt").read_text(encoding="utf-8").splitlines()[1:]
                             if l.strip() and l.strip() != "(none)"] if (out / "REVIEW_FLAGS.txt").exists() else []
        return self._send(200, body)

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(n) or b"{}")
        pid = payload.get("posting_id", "")
        tr = Tracker()
        if u.path == "/applied" and tr.get(pid):
            tr.set_status(pid, "applied", "submitted via userscript in real Chrome")
            return self._send(200, {"ok": True})
        if u.path == "/needs_input" and tr.get(pid):
            tr.set_status(pid, "needs_input", "; ".join(payload.get("unanswered", []))[:400])
            return self._send(200, {"ok": True})
        return self._send(404, {"error": "unknown posting or path"})


def serve():
    print(f"secjobs bridge listening on http://{HOST}:{PORT}  (Ctrl+C to stop)")
    print("Open any Lever apply page in your normal Chrome and click 'Fill from secjobs'.")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()

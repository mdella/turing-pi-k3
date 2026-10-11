#!/usr/bin/env python3
"""Render service for Hermes' render_docs MCP (k3s replacement for its `docker run … chromium` per job).

POST /render  {"files": {name: base64}, "page": name, "args": [...], "dump": bool}
          ->  {"rc": int, "stdout": str, "stderr": str, "outputs": {"out.png"|"out.pdf": base64}}
One job at a time (single-threaded server): /job is wiped, the files written there, headless Chromium runs on
file:///job/<page> with Mermaid at /vendor — the same paths the docker version mounted. Only known Chromium flags are
accepted from the client. The pod has no network egress (NetworkPolicy), so untrusted markup can't fetch anything.
"""
import base64, json, os, re, shutil, subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer

JOB = "/job"
TIMEOUT = int(os.environ.get("RENDER_TIMEOUT", "90"))
MAX_BODY = int(os.environ.get("RENDER_MAX_BODY", str(16 * 1024 * 1024)))
MAX_OUTPUT = int(os.environ.get("RENDER_MAX_OUTPUT", str(50 * 1024 * 1024)))
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
CHROME = ["chromium-browser", "--headless", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--no-first-run",
          "--user-data-dir=/tmp/profile", "--allow-file-access-from-files", "--hide-scrollbars",
          "--run-all-compositor-stages-before-draw", "--virtual-time-budget=20000"]
ALLOWED_ARGS = [re.compile(p) for p in (r"--window-size=\d{1,5},\d{1,5}", r"--force-device-scale-factor=\d(\.\d+)?",
                                         r"--screenshot=/job/out\.png", r"--print-to-pdf=/job/out\.pdf",
                                         r"--no-pdf-header-footer")]
OUTPUTS = ("out.png", "out.pdf")


def render(req):
    files, page, args, dump = req["files"], req["page"], req.get("args", []), bool(req.get("dump"))
    if page not in files or not all(isinstance(n, str) and NAME_RE.match(n) for n in files):
        raise ValueError("bad file names")
    if not all(isinstance(a, str) and any(p.fullmatch(a) for p in ALLOWED_ARGS) for a in args):
        raise ValueError("unsupported chromium argument")
    for entry in os.scandir(JOB):
        shutil.rmtree(entry.path) if entry.is_dir() else os.unlink(entry.path)
    shutil.rmtree("/tmp/profile", ignore_errors=True)
    for name, b64 in files.items():
        with open(os.path.join(JOB, name), "wb") as f:
            f.write(base64.b64decode(b64))
    cmd = CHROME + args + (["--dump-dom"] if dump else []) + [f"file:///job/{page}"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT, env={"HOME": "/tmp", "PATH": "/usr/bin:/bin"})
        rc, out, err = r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        rc, out, err = 124, "", f"rendering timed out after {TIMEOUT}s"
    outputs = {}
    for name in OUTPUTS:
        p = os.path.join(JOB, name)
        if os.path.isfile(p):
            if os.path.getsize(p) > MAX_OUTPUT:
                raise ValueError("output too large")
            outputs[name] = base64.b64encode(open(p, "rb").read()).decode()
    return {"rc": rc, "stdout": out, "stderr": "\n".join(err.strip().splitlines()[-5:]), "outputs": outputs}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(200, {"ok": True}) if self.path == "/healthz" else self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/render":
            return self._send(404, {"error": "not found"})
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_BODY:
            return self._send(413, {"error": "request too large"})
        try:
            self._send(200, render(json.loads(self.rfile.read(n))))
        except (ValueError, KeyError, TypeError) as e:
            self._send(400, {"error": str(e)})

    def log_message(self, fmt, *a):
        print("render:", fmt % a, flush=True)


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Handler).serve_forever()

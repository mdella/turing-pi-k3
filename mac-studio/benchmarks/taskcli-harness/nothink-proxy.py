#!/usr/bin/env python3
"""
nothink-proxy.py — sit between Claude Code and Ollama and force thinking OFF.

    ./nothink-proxy.py [--port 11555] [--upstream http://127.0.0.1:11434]
    OLLAMA_HOST_URL=http://127.0.0.1:11555 claude-local ...

WHY THIS EXISTS
qwen3.8 burns whole agent turns reasoning instead of acting (8.3 turns per build
vs qwen3.6's 40.3, one build managing 2 turns in 30 minutes), and upstream issue
#17911 reports that on qwen3.8:27b-mlx the entire answer sometimes lands in the
reasoning channel with EMPTY content -- which in an agent loop means no tool
call, so the turn is wasted. The obvious test is to turn thinking off and re-run.

It cannot be done from claude-local. Measured against this Ollama (0.32.15):

  sent on /v1/messages                       thinking emitted?
  think: false                               YES  (ignored)
  reasoning_effort: "none"                   YES  (ignored -- that workaround is
                                                  for /v1/chat/completions)
  thinking: {"type":"adaptive"}  <- CC sends YES
  no thinking field  <- MAX_THINKING_TOKENS=0 YES (absence means on)
  thinking: {"type":"disabled"}              NO   <- the only thing that works

and Claude Code never emits that form: --effort takes only low/medium/high/
xhigh/max, and MAX_THINKING_TOKENS=0 merely omits the field. So the field is
rewritten in flight here.

WHAT IT CHANGES
Exactly one thing, on POSTs whose path contains "messages": sets
    thinking = {"type": "disabled"}
and drops `output_config.effort`, which is meaningless once thinking is off and
which Ollama mis-maps for some Qwen3.8 templates (upstream #17906: xhigh -> high
is rejected by the Jinja template with an HTTP 500). Everything else -- headers,
body, streaming -- is passed through untouched.

STREAMING IS THE WHOLE DIFFICULTY
Claude Code streams. Buffering the response would serialise every turn and make
the timing meaningless, so upstream bytes are relayed as they arrive and the
chunked framing is re-emitted rather than reconstructed.
"""
import argparse
import json
import http.server
import socketserver
import sys
import threading
import urllib.error
import urllib.request

UPSTREAM = "http://127.0.0.1:11434"
STATS = {"seen": 0, "patched": 0}
LOCK = threading.Lock()


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _patch(self, body):
        """Force thinking off. Returns (new_body, patched?)."""
        try:
            d = json.loads(body)
        except Exception:
            return body, False
        if not isinstance(d, dict):
            return body, False
        d["thinking"] = {"type": "disabled"}
        oc = d.get("output_config")
        if isinstance(oc, dict):
            oc.pop("effort", None)
            if not oc:
                d.pop("output_config", None)
        return json.dumps(d).encode(), True

    def _relay(self, method):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""

        patched = False
        if method == "POST" and "messages" in self.path and body:
            body, patched = self._patch(body)
            with LOCK:
                STATS["seen"] += 1
                STATS["patched"] += int(patched)
                if STATS["seen"] % 10 == 0:
                    print(f"  [{STATS['patched']}/{STATS['seen']} patched]",
                          file=sys.stderr, flush=True)

        hdrs = {k: v for k, v in self.headers.items()
                if k.lower() not in ("host", "content-length", "connection")}
        req = urllib.request.Request(UPSTREAM + self.path, data=body or None,
                                     headers=hdrs, method=method)
        try:
            resp = urllib.request.urlopen(req, timeout=1800)
            status, rhdrs = resp.status, resp.headers
        except urllib.error.HTTPError as e:
            resp, status, rhdrs = e, e.code, e.headers
        except Exception as e:
            self.send_response(502)
            self.send_header("content-length", "0")
            self.end_headers()
            print(f"  upstream error: {e}", file=sys.stderr, flush=True)
            return

        chunked = (rhdrs.get("Transfer-Encoding", "").lower() == "chunked" or
                   rhdrs.get("Content-Type", "").startswith("text/event-stream"))
        self.send_response(status)
        for k, v in rhdrs.items():
            if k.lower() not in ("transfer-encoding", "connection", "content-length"):
                self.send_header(k, v)
        if chunked:
            self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        try:
            if chunked:
                while True:
                    chunk = resp.read(1024)
                    if not chunk:
                        break
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
            else:
                data = resp.read()
                self.wfile.write(data)
            self.wfile.flush()
        except Exception:
            pass

    def do_POST(self):
        self._relay("POST")

    def do_GET(self):
        self._relay("GET")

    def do_DELETE(self):
        self._relay("DELETE")


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=11555)
    ap.add_argument("--upstream", default=UPSTREAM)
    a = ap.parse_args()
    UPSTREAM = a.upstream
    print(f"nothink-proxy :{a.port} -> {UPSTREAM}  (forcing thinking=disabled)",
          file=sys.stderr, flush=True)
    Server(("127.0.0.1", a.port), Handler).serve_forever()

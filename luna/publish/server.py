"""luna-publish — a deliberately tiny MCP server (stdlib only) that lets the Luna assistant publish public
documents to GitLab Pages, and nothing else.

Tools: publish_document, list_documents, unpublish_document. Each one writes/reads exactly one GitLab project
(PUBLISH_PROJECT, e.g. luna/docs) via a *project access token* that cannot reach any other project. Documents are
Markdown files docs/<slug>.md; that project's CI renders them to https://pages.geekstyle.net/<project>/<slug>/.

Transport: MCP streamable HTTP, JSON responses only (no SSE), POST /mcp, bearer-token auth (MCP_TOKEN).
"""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GITLAB = os.environ["GITLAB_URL"].rstrip("/")
PROJECT = os.environ["PUBLISH_PROJECT"]                     # e.g. luna/docs
PAGES_BASE = os.environ["PAGES_BASE_URL"].rstrip("/")       # e.g. https://pages.geekstyle.net/luna/docs
GL_TOKEN = os.environ["GITLAB_TOKEN"]
MCP_TOKEN = os.environ["MCP_TOKEN"]
BRANCH = os.environ.get("PUBLISH_BRANCH", "main")
MAX_BYTES = 256 * 1024
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
PID = urllib.parse.quote(PROJECT, safe="")

TOOLS = [
    {
        "name": "publish_document",
        "description": (
            "Publish (or replace) a PUBLIC web page on the open internet at "
            f"{PAGES_BASE}/<slug>/. Anyone can read it. Only call this after the user has seen the final text and "
            "explicitly said to publish it. Content is Markdown; it goes live about a minute after publishing."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "URL name: lowercase letters, digits, hyphens (max 64)"},
                "title": {"type": "string", "description": "Page title"},
                "markdown": {"type": "string", "description": "Page body in Markdown (no raw HTML/scripts)"},
            },
            "required": ["slug", "title", "markdown"],
        },
    },
    {
        "name": "list_documents",
        "description": "List the public documents already published, with their URLs.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "unpublish_document",
        "description": "Remove a published public document (its page disappears after the next build, ~1 minute).",
        "inputSchema": {
            "type": "object",
            "properties": {"slug": {"type": "string"}},
            "required": ["slug"],
        },
    },
]


def gl(method, path, body=None):
    req = urllib.request.Request(
        f"{GITLAB}/api/v4/projects/{PID}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"PRIVATE-TOKEN": GL_TOKEN, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, None


def file_path(slug):
    return urllib.parse.quote(f"docs/{slug}.md", safe="")


def publish(args):
    slug, title, md = args.get("slug", ""), (args.get("title") or "").strip(), args.get("markdown", "")
    if not SLUG_RE.match(slug):
        return "Invalid slug: use lowercase letters, digits and hyphens (1-64 chars).", True
    if not title or "\n" in title:
        return "A one-line title is required.", True
    body = f"# {title}\n\n{md.strip()}\n"
    if len(body.encode()) > MAX_BYTES:
        return f"Document too large (max {MAX_BYTES // 1024} KB).", True
    exists, _ = gl("GET", f"/repository/files/{file_path(slug)}?ref={BRANCH}")
    action = "update" if exists == 200 else "create"
    status, _ = gl("POST", "/repository/commits", {
        "branch": BRANCH,
        "commit_message": f"{'Update' if action == 'update' else 'Publish'} {slug}: {title}",
        "actions": [{"action": action, "file_path": f"docs/{slug}.md", "content": body}],
    })
    if status not in (200, 201):
        return f"GitLab refused the commit (HTTP {status}).", True
    return f"{'Updated' if action == 'update' else 'Published'}: {PAGES_BASE}/{slug}/ (live in about a minute).", False


def list_docs(_args):
    status, tree = gl("GET", f"/repository/tree?path=docs&ref={BRANCH}&per_page=100")
    if status == 404:
        return "No documents published yet.", False
    if status != 200:
        return f"GitLab error (HTTP {status}).", True
    slugs = sorted(t["name"][:-3] for t in tree or [] if t["type"] == "blob" and t["name"].endswith(".md"))
    if not slugs:
        return "No documents published yet.", False
    return "\n".join(f"- {s}: {PAGES_BASE}/{s}/" for s in slugs), False


def unpublish(args):
    slug = args.get("slug", "")
    if not SLUG_RE.match(slug):
        return "Invalid slug.", True
    status, _ = gl("POST", "/repository/commits", {
        "branch": BRANCH,
        "commit_message": f"Unpublish {slug}",
        "actions": [{"action": "delete", "file_path": f"docs/{slug}.md"}],
    })
    if status not in (200, 201):
        return f"Could not remove '{slug}' (HTTP {status}) - check the name with list_documents.", True
    return f"Removed '{slug}'; the page disappears after the next build (~1 minute).", False


HANDLERS = {"publish_document": publish, "list_documents": list_docs, "unpublish_document": unpublish}


def rpc(msg):
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if mid is None:                       # notification (e.g. notifications/initialized)
        return None
    if method == "initialize":
        result = {
            "protocolVersion": params.get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "luna-publish", "version": "1.0.0"},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        fn = HANDLERS.get(params.get("name"))
        if not fn:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown tool"}}
        text, is_err = fn(params.get("arguments") or {})
        result = {"content": [{"type": "text", "text": text}], "isError": is_err}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj=None):
        data = json.dumps(obj).encode() if obj is not None else b""
        self.send_response(code)
        if obj is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/healthz":
            return self._send(200, {"ok": True})
        self._send(405)                   # no SSE stream

    def do_DELETE(self):
        self._send(200)

    def do_POST(self):
        if self.path.rstrip("/") != "/mcp":
            return self._send(404)
        if self.headers.get("Authorization", "") != f"Bearer {MCP_TOKEN}":
            return self._send(401, {"error": "unauthorized"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n > 2 * MAX_BYTES:
                return self._send(413)
            msg = json.loads(self.rfile.read(n))
        except Exception:
            return self._send(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
        if isinstance(msg, list):
            out = [r for r in (rpc(m) for m in msg) if r is not None]
            return self._send(200, out) if out else self._send(202)
        res = rpc(msg)
        return self._send(200, res) if res is not None else self._send(202)

    def log_message(self, fmt, *a):      # one line per request, no bodies/tokens
        print(f"{self.address_string()} {fmt % a}", flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()

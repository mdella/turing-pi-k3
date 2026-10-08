"""repo_files — a small stdio MCP server that lets one Hermes profile maintain a fixed set of GitLab repos (read, write,
delete files as commits), and nothing else.

Repos come from REPO_FILES_CONFIG (JSON): {"<alias>": {"project": "group/project", "token_env": "ENV_VAR_WITH_TOKEN",
"public": true|false, "pages_base": "https://pages.../", "write_prefix": "docs/"}}. Each repo uses its own *project
access token* (can't reach other projects). Guards: never writes CI or build files (.gitlab-ci.yml, build.py — a CI file
is code that runs on the cluster's runner); `write_prefix` limits where writes may land (the public Pages repo: docs/).
Uploads of local files only from the profile's media caches (UPLOAD_ROOTS).

GitLab is reached in-cluster (GITLAB_URL + GITLAB_HOST header), not via Cloudflare (its bot protection blocks
non-browser clients). Repo: turing-pi-k3/hermes/mcp/repo_files.py.
"""
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

GITLAB = os.environ.get("GITLAB_URL", "http://192.168.4.201").rstrip("/")
HOST = os.environ.get("GITLAB_HOST", "scm.geekstyle.net")
REPOS = json.loads(os.environ["REPO_FILES_CONFIG"])
ROOTS = [Path(p).resolve() for p in os.environ.get("UPLOAD_ROOTS", "").split(":") if p]
BRANCH = "main"
MAX_TEXT = 512 * 1024
MAX_UPLOAD = 20 * 1024 * 1024
PATH_RE = re.compile(r"^(?!/)(?!.*(^|/)\.\.?(/|$))[\w\-. /()+,@=]{1,300}$")
FORBIDDEN = re.compile(r"(^|/)(\.gitlab-ci\.ya?ml|build\.py|\.gitlab/)", re.I)


class ToolError(Exception):
    pass


def _repo(args):
    alias = args.get("repo") or ""
    if alias not in REPOS:
        raise ToolError(f"repo must be one of: {', '.join(REPOS)}")
    r = dict(REPOS[alias])
    r["token"] = os.environ.get(r["token_env"], "")
    r["pid"] = urllib.parse.quote(r["project"], safe="")
    return alias, r


def _path(p, r=None, write=False):
    p = (p or "").strip()
    if not PATH_RE.match(p):
        raise ToolError("invalid path: letters, digits, - _ . / ( ) and spaces; no leading '/' or '..'")
    if write:
        if FORBIDDEN.search(p):
            raise ToolError("CI and build files can't be changed through this tool (ask the owner)")
        pre = (r or {}).get("write_prefix")
        if pre and not p.startswith(pre):
            raise ToolError(f"in this repo you can only write under {pre}")
    return p


def gl(r, method, sub, body=None):
    req = urllib.request.Request(
        f"{GITLAB}/api/v4/projects/{r['pid']}{sub}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"PRIVATE-TOKEN": r["token"], "Content-Type": "application/json", "Host": HOST,
                 "User-Agent": "hermes-repo-files/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, None


def _exists(r, path):
    st, _ = gl(r, "GET", f"/repository/files/{urllib.parse.quote(path, safe='')}?ref={BRANCH}")
    return st == 200


def _commit(r, msg, actions):
    st, res = gl(r, "POST", "/repository/commits", {"branch": BRANCH, "commit_message": f"[cheshire] {msg}"[:200],
                                                       "actions": actions})
    if st not in (200, 201):
        raise ToolError(f"GitLab refused the commit (HTTP {st})")
    return res.get("short_id", "")


def _url_hint(r, path):
    base = r.get("pages_base")
    if not base or not path.endswith(".md") or "/" in path[len(r.get("write_prefix", "")):]:
        return ""
    slug = Path(path).stem
    return f" Public page (live in ~1 min): {base.rstrip('/')}/{slug}/"


TOOLS_DESC = {a: ("PUBLIC website" if c.get("public") else "private repo") for a, c in REPOS.items()}
REPO_PROP = {"type": "string", "enum": list(REPOS),
             "description": "; ".join(f"'{a}' = {d} ({REPOS[a]['project']})" for a, d in TOOLS_DESC.items())}
TOOLS = [
    {"name": "repo_list", "description": "List files and folders in a repo (optionally under a path).",
     "inputSchema": {"type": "object", "properties": {"repo": REPO_PROP, "path": {"type": "string"},
                                                       "recursive": {"type": "boolean", "default": False}},
                     "required": ["repo"]}},
    {"name": "repo_read", "description": "Read a text file from a repo (max 512 KB).",
     "inputSchema": {"type": "object", "properties": {"repo": REPO_PROP, "path": {"type": "string"}},
                     "required": ["repo", "path"]}},
    {"name": "repo_write", "description": (
        "Create or replace a text file (one commit). For a PUBLIC repo the result is on the open internet: only after "
        "the owner saw the final text and explicitly said to publish. Pages: write Markdown to docs/<name>.md "
        "(first line '# Title'); images go to docs/assets/ and are linked as ../assets/<file>."),
     "inputSchema": {"type": "object", "properties": {
         "repo": REPO_PROP, "path": {"type": "string"}, "content": {"type": "string"},
         "message": {"type": "string", "description": "Short commit message"}}, "required": ["repo", "path", "content"]}},
    {"name": "repo_upload_file", "description": (
        "Commit a local file you received or generated (e.g. an image) into a repo, e.g. docs/assets/photo.jpg. "
        "Same publishing rules as repo_write for a public repo."),
     "inputSchema": {"type": "object", "properties": {
         "repo": REPO_PROP, "local_path": {"type": "string"}, "path": {"type": "string"},
         "message": {"type": "string"}}, "required": ["repo", "local_path", "path"]}},
    {"name": "repo_delete", "description": "Delete a file (one commit). Confirm with the owner first.",
     "inputSchema": {"type": "object", "properties": {"repo": REPO_PROP, "path": {"type": "string"},
                                                       "message": {"type": "string"}}, "required": ["repo", "path"]}},
]


def t_list(a):
    alias, r = _repo(a)
    q = {"ref": BRANCH, "per_page": "100", "recursive": "true" if a.get("recursive") else "false"}
    if a.get("path"):
        q["path"] = _path(a["path"])
    st, items = gl(r, "GET", "/repository/tree?" + urllib.parse.urlencode(q))
    if st == 404:
        return "Nothing there."
    if st != 200:
        raise ToolError(f"GitLab error (HTTP {st})")
    return "\n".join(f"{'📁' if i['type'] == 'tree' else '-'} {i['path']}" for i in items) or "Empty."


def t_read(a):
    alias, r = _repo(a)
    p = _path(a.get("path"))
    st, f = gl(r, "GET", f"/repository/files/{urllib.parse.quote(p, safe='')}?ref={BRANCH}")
    if st == 404:
        raise ToolError("file not found")
    if st != 200:
        raise ToolError(f"GitLab error (HTTP {st})")
    if f.get("size", 0) > MAX_TEXT:
        raise ToolError("file too large to read here")
    data = base64.b64decode(f.get("content", ""))
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise ToolError("not a text file")


def t_write(a):
    alias, r = _repo(a)
    p = _path(a.get("path"), r, write=True)
    content = a.get("content") or ""
    if len(content.encode()) > MAX_TEXT:
        raise ToolError("content too large")
    action = "update" if _exists(r, p) else "create"
    sha = _commit(r, a.get("message") or f"{action} {p}", [{"action": action, "file_path": p, "content": content}])
    return f"{'Updated' if action == 'update' else 'Created'} {p} in {alias} (commit {sha}).{_url_hint(r, p)}"


def t_upload(a):
    alias, r = _repo(a)
    p = _path(a.get("path"), r, write=True)
    src = Path(a.get("local_path") or "").expanduser().resolve()
    if not any(src == root or root in src.parents for root in ROOTS):
        raise ToolError("only files from your media cache can be uploaded")
    if not src.is_file() or src.stat().st_size > MAX_UPLOAD:
        raise ToolError("file missing or larger than 20 MB")
    action = "update" if _exists(r, p) else "create"
    sha = _commit(r, a.get("message") or f"{action} {p}", [{"action": action, "file_path": p, "encoding": "base64",
                                                            "content": base64.b64encode(src.read_bytes()).decode()}])
    return f"Uploaded {p} to {alias} (commit {sha})."


def t_delete(a):
    alias, r = _repo(a)
    p = _path(a.get("path"), r, write=True)
    if not _exists(r, p):
        raise ToolError("file not found")
    sha = _commit(r, a.get("message") or f"delete {p}", [{"action": "delete", "file_path": p}])
    return f"Deleted {p} from {alias} (commit {sha})."


HANDLERS = {"repo_list": t_list, "repo_read": t_read, "repo_write": t_write, "repo_upload_file": t_upload,
            "repo_delete": t_delete}


def rpc(msg):
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if mid is None:
        return None
    if method == "initialize":
        res = {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
               "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "repo_files", "version": "1.0.0"}}
    elif method == "ping":
        res = {}
    elif method == "tools/list":
        res = {"tools": TOOLS}
    elif method == "tools/call":
        fn = HANDLERS.get(params.get("name"))
        try:
            text, err = (fn(params.get("arguments") or {}), False) if fn else ("unknown tool", True)
        except ToolError as e:
            text, err = str(e), True
        except (OSError, ValueError) as e:
            text, err = f"GitLab unavailable: {type(e).__name__}", True
        res = {"content": [{"type": "text", "text": text}], "isError": err}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": res}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        for r in (x for x in (rpc(m) for m in (msg if isinstance(msg, list) else [msg])) if x is not None):
            sys.stdout.write(json.dumps(r) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()

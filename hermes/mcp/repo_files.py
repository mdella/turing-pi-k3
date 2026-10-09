"""repo_files — a small stdio MCP server that lets one Hermes profile maintain a fixed set of GitLab repos (read, write,
delete files as commits), and nothing else.

Repos come from REPO_FILES_CONFIG (JSON): {"<alias>": {"project": "group/project", "token_env": "ENV_VAR_WITH_TOKEN",
"public": true|false, "pages_base": "https://pages.../", "write_prefix": "docs/"}}. Each alias uses its own *project
access token* (can't reach other projects).

Bot mode (optional, 2026-10-09): REPO_FILES_BOT (JSON) {"token_env": "...", "name": "cheshire-bot",
"allowed_prefixes": ["group/sub/", ...]} — any project under those namespaces can be named by its full path and is
reached with the bot's own token, so GitLab's role/branch protection is the real boundary (protected default branches
need Maintainer; otherwise commit to a branch and open a merge request). Can also create PRIVATE projects there. Guards: never writes CI or build files (.gitlab-ci.yml, build.py — a CI file
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
REPOS = json.loads(os.environ.get("REPO_FILES_CONFIG") or "{}")
BOT = json.loads(os.environ.get("REPO_FILES_BOT") or "{}")
BOT_PREFIXES = [p.rstrip("/") + "/" for p in BOT.get("allowed_prefixes", [])]
COMMIT_PREFIX = os.environ.get("REPO_FILES_COMMIT_PREFIX", "[assistant]")
PROJ_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*(/[a-z0-9][a-z0-9_.-]*){1,6}$", re.I)
ROOTS = [Path(p).resolve() for p in os.environ.get("UPLOAD_ROOTS", "").split(":") if p]
BRANCH = "main"
MAX_TEXT = 512 * 1024
MAX_UPLOAD = 20 * 1024 * 1024
PATH_RE = re.compile(r"^(?!/)(?!.*(^|/)\.\.?(/|$))[\w\-. /()+,@=]{1,300}$")
FORBIDDEN = re.compile(r"(^|/)(\.gitlab-ci\.ya?ml|build\.py|\.gitlab/)", re.I)


class ToolError(Exception):
    pass


def _bot_allowed(path):
    return any(path.startswith(pre) for pre in BOT_PREFIXES)


def _repo(args):
    alias = (args.get("repo") or "").strip()
    if alias in REPOS:
        r = dict(REPOS[alias])
        r["token"] = os.environ.get(r["token_env"], "")
    elif BOT and PROJ_RE.match(alias) and _bot_allowed(alias):
        r = {"project": alias, "token": os.environ.get(BOT["token_env"], ""), "bot": True, "public": False}
    else:
        opts = list(REPOS) + ([f"any project under {', '.join(BOT_PREFIXES)}"] if BOT else [])
        raise ToolError(f"repo must be one of: {'; '.join(opts)}")
    r["pid"] = urllib.parse.quote(r["project"], safe="")
    return alias, r


def _branch(r, args, write=False):
    """Requested branch (default: the project's default branch). For writes to a branch that doesn't exist yet,
    returns start_branch so the commit creates it from the default branch."""
    st, proj = gl(r, "GET", "")
    if st != 200:
        raise ToolError("project not found or not accessible")
    default = proj.get("default_branch") or "main"
    want = (args.get("branch") or "").strip() or default
    if not re.match(r"^[\w./-]{1,100}$", want) or ".." in want:
        raise ToolError("invalid branch name")
    if not write or want == default:
        return want, None
    st, _ = gl(r, "GET", f"/repository/branches/{urllib.parse.quote(want, safe='')}")
    return want, (None if st == 200 else default)


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


def _exists(r, path, ref=BRANCH):
    st, _ = gl(r, "GET", f"/repository/files/{urllib.parse.quote(path, safe='')}?ref={urllib.parse.quote(ref, safe='')}")
    return st == 200


def _commit(r, msg, actions, branch=BRANCH, start_branch=None):
    body = {"branch": branch, "commit_message": f"{COMMIT_PREFIX} {msg}"[:200], "actions": actions}
    if start_branch:
        body["start_branch"] = start_branch
    st, res = gl(r, "POST", "/repository/commits", body)
    if st == 403:
        raise ToolError(f"GitLab refused: '{branch}' is protected for this account — commit to a new branch "
                        "(set branch) and open a merge request instead")
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
_desc = "; ".join(f"'{a}' = {d} ({REPOS[a]['project']})" for a, d in TOOLS_DESC.items())
if BOT:
    _desc = (_desc + "; " if _desc else "") + (f"or the full path of any repo under {', '.join(BOT_PREFIXES)} "
                                               f"(as {BOT.get('name', 'your bot account')}; see repo_projects)")
REPO_PROP = {"type": "string", "description": _desc} if BOT else {"type": "string", "enum": list(REPOS), "description": _desc}
BRANCH_PROP = {"type": "string", "description": "Branch (default: the repo's default branch). A new name creates the "
               "branch from the default branch — use that for protected repos, then open a merge request."}
TOOLS = [
    {"name": "repo_projects", "description": "List the repos you can work in.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "repo_create_project", "description": "Create a new PRIVATE repo (with README) in an allowed group. Confirm first.",
     "inputSchema": {"type": "object", "properties": {"namespace": {"type": "string"}, "name": {"type": "string"},
                                                       "description": {"type": "string"}}, "required": ["namespace", "name"]}},
    {"name": "repo_list", "description": "List files and folders in a repo (optionally under a path).",
     "inputSchema": {"type": "object", "properties": {"repo": REPO_PROP, "path": {"type": "string"},
                                                       "recursive": {"type": "boolean", "default": False},
                                                       "branch": BRANCH_PROP},
                     "required": ["repo"]}},
    {"name": "repo_read", "description": "Read a text file from a repo (max 512 KB).",
     "inputSchema": {"type": "object", "properties": {"repo": REPO_PROP, "path": {"type": "string"},
                                                       "branch": BRANCH_PROP}, "required": ["repo", "path"]}},
    {"name": "repo_write", "description": (
        "Create or replace a text file (one commit). For a PUBLIC repo the result is on the open internet: only after "
        "the owner saw the final text and explicitly said to publish. Pages: write Markdown to docs/<name>.md "
        "(first line '# Title'); images go to docs/assets/ and are linked as ../assets/<file>."),
     "inputSchema": {"type": "object", "properties": {
         "repo": REPO_PROP, "path": {"type": "string"}, "content": {"type": "string"},
         "message": {"type": "string", "description": "Short commit message"}, "branch": BRANCH_PROP},
                     "required": ["repo", "path", "content"]}},
    {"name": "repo_upload_file", "description": (
        "Commit a local file you received or generated (e.g. an image) into a repo, e.g. docs/assets/photo.jpg. "
        "Same publishing rules as repo_write for a public repo."),
     "inputSchema": {"type": "object", "properties": {
         "repo": REPO_PROP, "local_path": {"type": "string"}, "path": {"type": "string"},
         "message": {"type": "string"}, "branch": BRANCH_PROP}, "required": ["repo", "local_path", "path"]}},
    {"name": "repo_delete", "description": "Delete a file (one commit). Confirm with the owner first.",
     "inputSchema": {"type": "object", "properties": {"repo": REPO_PROP, "path": {"type": "string"},
                                                       "message": {"type": "string"}, "branch": BRANCH_PROP},
                     "required": ["repo", "path"]}},
]


def t_list(a):
    alias, r = _repo(a)
    ref, _ = _branch(r, a) if r.get("bot") else (BRANCH, None)
    q = {"ref": ref, "per_page": "100", "recursive": "true" if a.get("recursive") else "false"}
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
    ref, _ = _branch(r, a) if r.get("bot") else (BRANCH, None)
    st, f = gl(r, "GET", f"/repository/files/{urllib.parse.quote(p, safe='')}?ref={urllib.parse.quote(ref, safe='')}")
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
    br, start = _branch(r, a, write=True) if r.get("bot") else (BRANCH, None)
    action = "update" if _exists(r, p, start or br) else "create"
    sha = _commit(r, a.get("message") or f"{action} {p}", [{"action": action, "file_path": p, "content": content}],
                  br, start)
    where = f" on branch {br}" + (f" (new, from {start})" if start else "") if r.get("bot") else ""
    return f"{'Updated' if action == 'update' else 'Created'} {p} in {alias}{where} (commit {sha}).{_url_hint(r, p)}"


def t_upload(a):
    alias, r = _repo(a)
    p = _path(a.get("path"), r, write=True)
    src = Path(a.get("local_path") or "").expanduser().resolve()
    if not any(src == root or root in src.parents for root in ROOTS):
        raise ToolError("only files from your media cache can be uploaded")
    if not src.is_file() or src.stat().st_size > MAX_UPLOAD:
        raise ToolError("file missing or larger than 20 MB")
    br, start = _branch(r, a, write=True) if r.get("bot") else (BRANCH, None)
    action = "update" if _exists(r, p, start or br) else "create"
    sha = _commit(r, a.get("message") or f"{action} {p}", [{"action": action, "file_path": p, "encoding": "base64",
                                                            "content": base64.b64encode(src.read_bytes()).decode()}],
                  br, start)
    return f"Uploaded {p} to {alias} on {br} (commit {sha})."


def t_delete(a):
    alias, r = _repo(a)
    p = _path(a.get("path"), r, write=True)
    br, start = _branch(r, a, write=True) if r.get("bot") else (BRANCH, None)
    if not _exists(r, p, start or br):
        raise ToolError("file not found")
    sha = _commit(r, a.get("message") or f"delete {p}", [{"action": "delete", "file_path": p}], br, start)
    return f"Deleted {p} from {alias} on {br} (commit {sha})."


def _bot_req(method, url_path, body=None):
    r = {"token": os.environ.get(BOT.get("token_env", ""), ""), "pid": ""}
    req = urllib.request.Request(f"{GITLAB}/api/v4{url_path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"PRIVATE-TOKEN": r["token"], "Content-Type": "application/json", "Host": HOST,
                                          "User-Agent": "hermes-repo-files/1.1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, None


def t_projects(a):
    if not BOT:
        return "Repos: " + ", ".join(f"{k} ({v['project']})" for k, v in REPOS.items())
    st, items = _bot_req("GET", "/projects?membership=true&per_page=100&simple=true&order_by=path&sort=asc")
    if st != 200:
        raise ToolError(f"GitLab error (HTTP {st})")
    rows = [f"- {p['path_with_namespace']} ({p.get('visibility')})" for p in items or [] if _bot_allowed(p['path_with_namespace'])]
    alias = [f"- '{k}' = {v['project']}" for k, v in REPOS.items()]
    return "\n".join((["Shortcuts:"] + alias if alias else []) + ["Repos you can reach:"] + (rows or ["(none yet)"]))


def t_create(a):
    if not BOT:
        raise ToolError("creating repos isn't enabled for you")
    ns = (a.get("namespace") or "").strip().rstrip("/")
    name = (a.get("name") or "").strip()
    if not (ns + "/") in BOT_PREFIXES and not _bot_allowed(ns + "/"):
        raise ToolError(f"namespace must be one of / under: {', '.join(p.rstrip('/') for p in BOT_PREFIXES)}")
    if not re.match(r"^[a-z0-9][a-z0-9_.-]{0,62}$", name, re.I):
        raise ToolError("name: letters, digits, - _ . (max 63)")
    st, grp = _bot_req("GET", "/groups/" + urllib.parse.quote(ns, safe=""))
    if st != 200:
        raise ToolError("namespace not found or not accessible")
    st, p = _bot_req("POST", "/projects", {"name": name, "path": name, "namespace_id": grp["id"], "visibility": "private",
                                           "initialize_with_readme": True, "default_branch": "main",
                                           "description": (a.get("description") or "")[:250]})
    if st not in (200, 201):
        raise ToolError(f"GitLab refused to create it (HTTP {st}) — maybe it already exists")
    return f"Created private repo {p['path_with_namespace']} ({p['web_url']})."


HANDLERS = {"repo_projects": t_projects, "repo_create_project": t_create, "repo_list": t_list, "repo_read": t_read, "repo_write": t_write, "repo_upload_file": t_upload,
            "repo_delete": t_delete}


def rpc(msg):
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if mid is None:
        return None
    if method == "initialize":
        res = {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
               "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "repo_files", "version": "1.1.0"}}
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

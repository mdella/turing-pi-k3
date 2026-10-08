"""s3_store — a small stdio MCP server that gives one Hermes profile its own S3 storage (SeaweedFS).

Two buckets per profile: "mine" (S3_BUCKET_OWN, e.g. hermes-cheshire) and "shared" (S3_BUCKET_SHARED, hermes-shared),
both reached with that profile's own scoped S3 key — SeaweedFS refuses everything else server-side, so this file is
convenience, not the security boundary. Uploads read local files only from the profile's media caches
(S3_UPLOAD_ROOTS), downloads land in <profile>/cache/s3-downloads so other tools (vision, …) can use them.

Transport: MCP over stdio (newline-delimited JSON-RPC). Hermes launches it per profile (mcp_servers.s3 in that
profile's config.yaml) with the credentials in its env. Repo: turing-pi-k3/hermes/mcp/s3_store.py.
"""
import json
import mimetypes
import os
import re
import sys
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

ENDPOINT = os.environ["S3_ENDPOINT"]                                  # used for API calls
LINK_ENDPOINT = os.environ.get("S3_LINK_ENDPOINT") or ENDPOINT         # used in share links
BUCKETS = {"mine": os.environ["S3_BUCKET_OWN"], "shared": os.environ["S3_BUCKET_SHARED"]}
ROOTS = [Path(p).resolve() for p in os.environ.get("S3_UPLOAD_ROOTS", "").split(":") if p]
DOWNLOAD_DIR = Path(os.environ["S3_DOWNLOAD_DIR"])
MAX_BYTES = int(os.environ.get("S3_MAX_BYTES", str(200 * 1024 * 1024)))
MAX_TEXT = 256 * 1024
KEY_RE = re.compile(r"^(?!/)(?!.*(^|/)\.\.?(/|$))[\w\-. /()+,@=]{1,512}$")

_cfg = Config(s3={"addressing_style": "path"}, retries={"max_attempts": 3}, signature_version="s3v4")
_kw = dict(aws_access_key_id=os.environ["S3_ACCESS_KEY"], aws_secret_access_key=os.environ["S3_SECRET_KEY"],
           region_name="us-east-1", config=_cfg)
s3 = boto3.client("s3", endpoint_url=ENDPOINT, **_kw)
s3_links = boto3.client("s3", endpoint_url=LINK_ENDPOINT, **_kw)

BUCKET_PROP = {"type": "string", "enum": ["mine", "shared"], "default": "mine",
               "description": "'mine' = your own storage, 'shared' = storage shared with the other assistant"}
TOOLS = [
    {"name": "s3_list", "description": "List stored files (name, size, last modified).",
     "inputSchema": {"type": "object", "properties": {
         "bucket": BUCKET_PROP, "prefix": {"type": "string", "description": "Only names starting with this"},
         "limit": {"type": "integer", "default": 100, "maximum": 1000}}}},
    {"name": "s3_upload_file", "description": (
        "Store a local file (an image or document the user sent, or one you generated) in S3. `path` must be a file "
        "in your media cache. Returns the stored name."),
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"}, "key": {"type": "string", "description": "Stored name, e.g. photos/2026/cat.jpg (default: file name)"},
         "bucket": BUCKET_PROP}, "required": ["path"]}},
    {"name": "s3_put_text", "description": "Store text (notes, Markdown, JSON, CSV …) as a file in S3.",
     "inputSchema": {"type": "object", "properties": {
         "key": {"type": "string"}, "text": {"type": "string"}, "bucket": BUCKET_PROP,
         "content_type": {"type": "string", "default": "text/markdown; charset=utf-8"}}, "required": ["key", "text"]}},
    {"name": "s3_get_text", "description": "Read a stored text file (max 256 KB).",
     "inputSchema": {"type": "object", "properties": {"key": {"type": "string"}, "bucket": BUCKET_PROP},
                     "required": ["key"]}},
    {"name": "s3_download", "description": (
        "Fetch a stored file to a local path so other tools (e.g. image analysis) can use it. Returns the path."),
     "inputSchema": {"type": "object", "properties": {"key": {"type": "string"}, "bucket": BUCKET_PROP},
                     "required": ["key"]}},
    {"name": "s3_share_link", "description": (
        "Make a time-limited https download link for a stored file (works at home / over netbird, not on the public "
        "internet). Default 60 minutes, max 7 days."),
     "inputSchema": {"type": "object", "properties": {
         "key": {"type": "string"}, "bucket": BUCKET_PROP,
         "expires_minutes": {"type": "integer", "default": 60, "maximum": 10080}}, "required": ["key"]}},
    {"name": "s3_delete", "description": "Delete a stored file. Confirm with the user first.",
     "inputSchema": {"type": "object", "properties": {"key": {"type": "string"}, "bucket": BUCKET_PROP},
                     "required": ["key"]}},
]


class ToolError(Exception):
    pass


def _bucket(args):
    b = args.get("bucket") or "mine"
    if b not in BUCKETS:
        raise ToolError("bucket must be 'mine' or 'shared'")
    return BUCKETS[b]


def _key(k):
    k = (k or "").strip()
    if not KEY_RE.match(k):
        raise ToolError("invalid name: use letters, digits, - _ . / ( ) and spaces; no leading '/' or '..'")
    return k


def _human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def t_list(a):
    b, prefix, limit = _bucket(a), a.get("prefix") or "", min(int(a.get("limit") or 100), 1000)
    r = s3.list_objects_v2(Bucket=b, Prefix=prefix, MaxKeys=limit)
    items = r.get("Contents", [])
    if not items:
        return "No files" + (f" starting with '{prefix}'." if prefix else ".")
    lines = [f"- {o['Key']}  ({_human(o['Size'])}, {o['LastModified']:%Y-%m-%d %H:%M} UTC)" for o in items]
    more = "\n(more files exist — narrow with prefix)" if r.get("IsTruncated") else ""
    return "\n".join(lines) + more


def t_upload(a):
    p = Path(a.get("path") or "").expanduser().resolve()
    if not any(p == r or r in p.parents for r in ROOTS):
        raise ToolError("that file is outside your media cache; only files you received or generated can be stored")
    if not p.is_file():
        raise ToolError("file not found")
    if p.stat().st_size > MAX_BYTES:
        raise ToolError(f"file too large (max {MAX_BYTES // (1024 * 1024)} MB)")
    k, b = _key(a.get("key") or p.name), _bucket(a)
    ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    s3.upload_file(str(p), b, k, ExtraArgs={"ContentType": ctype})
    return f"Stored as '{k}' in {a.get('bucket') or 'mine'} ({_human(p.stat().st_size)})."


def t_put_text(a):
    k, b, text = _key(a.get("key")), _bucket(a), a.get("text") or ""
    data = text.encode()
    if len(data) > MAX_BYTES:
        raise ToolError("text too large")
    s3.put_object(Bucket=b, Key=k, Body=data, ContentType=a.get("content_type") or "text/markdown; charset=utf-8")
    return f"Stored '{k}' in {a.get('bucket') or 'mine'} ({_human(len(data))})."


def t_get_text(a):
    k, b = _key(a.get("key")), _bucket(a)
    head = s3.head_object(Bucket=b, Key=k)
    if head["ContentLength"] > MAX_TEXT:
        raise ToolError("file larger than 256 KB — use s3_download instead")
    body = s3.get_object(Bucket=b, Key=k)["Body"].read()
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        raise ToolError("not a text file — use s3_download instead")


def t_download(a):
    k, b = _key(a.get("key")), _bucket(a)
    head = s3.head_object(Bucket=b, Key=k)
    if head["ContentLength"] > MAX_BYTES:
        raise ToolError("file too large to download here")
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = DOWNLOAD_DIR / k.replace("/", "__")
    s3.download_file(b, k, str(dest))
    return f"Downloaded to {dest}"


def t_share(a):
    k, b = _key(a.get("key")), _bucket(a)
    s3.head_object(Bucket=b, Key=k)
    mins = max(1, min(int(a.get("expires_minutes") or 60), 10080))
    url = s3_links.generate_presigned_url("get_object", Params={"Bucket": b, "Key": k}, ExpiresIn=mins * 60)
    return f"{url}\n(valid {mins} minutes; reachable at home or over netbird)"


def t_delete(a):
    k, b = _key(a.get("key")), _bucket(a)
    s3.head_object(Bucket=b, Key=k)
    s3.delete_object(Bucket=b, Key=k)
    return f"Deleted '{k}'."


HANDLERS = {"s3_list": t_list, "s3_upload_file": t_upload, "s3_put_text": t_put_text, "s3_get_text": t_get_text,
            "s3_download": t_download, "s3_share_link": t_share, "s3_delete": t_delete}


def call(name, args):
    fn = HANDLERS.get(name)
    if not fn:
        return "unknown tool", True
    try:
        return fn(args or {}), False
    except ToolError as e:
        return str(e), True
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        msg = {"404": "not found", "NoSuchKey": "not found", "AccessDenied": "access denied"}.get(code, code or "S3 error")
        return f"S3: {msg}", True
    except (BotoCoreError, OSError) as e:
        return f"storage unavailable: {type(e).__name__}", True


def rpc(msg):
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if mid is None:
        return None
    if method == "initialize":
        res = {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
               "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "s3_store", "version": "1.0.0"}}
    elif method == "ping":
        res = {}
    elif method == "tools/list":
        res = {"tools": TOOLS}
    elif method == "tools/call":
        text, err = call(params.get("name"), params.get("arguments"))
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
        msgs = msg if isinstance(msg, list) else [msg]
        out = [r for r in (rpc(m) for m in msgs) if r is not None]
        for r in out:
            sys.stdout.write(json.dumps(r) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()

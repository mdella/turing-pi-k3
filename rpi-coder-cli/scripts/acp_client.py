# Minimal ACP-over-HTTP client for the Pi's goose-agent service (stdlib only).
#   GOOSE_SERVER__SECRET_KEY=... python3 acp_client.py http://100.101.77.5:3284/acp <cwd-on-pi> "<prompt>"
#
# Transport as observed on goose 1.52 (`goose serve`):
#   * every request carries  X-Secret-Key: <GOOSE_SERVER__SECRET_KEY>
#   * POST initialize         -> 200 with the JSON-RPC result and an `acp-connection-id` header
#   * GET  (Accept: text/event-stream, acp-connection-id) -> connection SSE stream; carries the
#     session/new result
#   * GET  (… + acp-session-id) -> session SSE stream; carries session/prompt results and all
#     session/update notifications (message chunks, tool calls)
#   * POST session/new (acp-connection-id) and session/prompt (+ acp-session-id) -> 202; the answer
#     arrives on the matching SSE stream, not in the POST response
import json, os, queue, sys, threading, urllib.request
URL, CWD, PROMPT = sys.argv[1], sys.argv[2], sys.argv[3]
KEY = os.environ["GOOSE_SERVER__SECRET_KEY"]
BASE = {"X-Secret-Key": KEY}
events = queue.Queue()

def post(msg, conn=None, sid=None):
    h = dict(BASE, **{"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
    if conn: h["acp-connection-id"] = conn
    if sid: h["acp-session-id"] = sid
    r = urllib.request.urlopen(urllib.request.Request(URL, json.dumps(msg).encode(), h), timeout=60)
    return r.headers.get("acp-connection-id"), r.read().decode()

def listen(conn, sid=None):
    h = dict(BASE, **{"Accept": "text/event-stream", "acp-connection-id": conn})
    if sid: h["acp-session-id"] = sid
    with urllib.request.urlopen(urllib.request.Request(URL, headers=h), timeout=900) as r:
        for raw in r:
            line = raw.decode().strip()
            if line.startswith("data:") and line[5:].strip():
                events.put(json.loads(line[5:]))

def wait_for(rid, on_update=None):
    while True:
        x = events.get(timeout=900)
        if x.get("id") == rid and ("result" in x or "error" in x):
            return x
        if on_update and x.get("method") == "session/update":
            on_update(x["params"]["update"])

conn, body = post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": 1, "clientCapabilities": {}}})
print("agent", json.loads(body)["result"]["agentInfo"])
threading.Thread(target=listen, args=(conn,), daemon=True).start()
post({"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {"cwd": CWD, "mcpServers": []}}, conn)
sid = wait_for(2)["result"]["sessionId"]
print("session", sid)
threading.Thread(target=listen, args=(conn, sid), daemon=True).start()
import time; time.sleep(0.5)   # let the session stream attach before prompting

text, tools = [], []
def on_update(u):
    k = u.get("sessionUpdate")
    if k == "agent_message_chunk": text.append((u.get("content") or {}).get("text", ""))
    elif k == "tool_call": tools.append(u.get("title") or u.get("kind"))

post({"jsonrpc": "2.0", "id": 3, "method": "session/prompt",
      "params": {"sessionId": sid, "prompt": [{"type": "text", "text": PROMPT}]}}, conn, sid)
res = wait_for(3, on_update)
print("stopReason", (res.get("result") or {}).get("stopReason"), res.get("error") or "")
print("tools", tools)
print("answer", "".join(text).strip()[:800])

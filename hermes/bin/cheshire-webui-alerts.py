#!/usr/bin/env python3
"""Post Cheshire's scheduled-job results into a chat in her Open WebUI (cheshire.geekstyle.net).

Hermes can't push cron output to Open WebUI: Cheshire's chat reaches her through the api_server platform, which only
answers requests (cron/scheduler_delivery.py lists it in _NON_PUSH_ORIGIN_PLATFORMS). So her jobs use deliver=local,
which writes one Markdown file per run to cron/output/<job id>/, and this script forwards those files.

Every run: for each of Cheshire's jobs with deliver=local, read the run files newer than the last one forwarded.
"[SILENT]" responses are skipped; any other response becomes an assistant message in the chat "Cheshire alerts",
and the chat is marked unread. A failed run ("[CRON_FAILURE]") is forwarded only when it starts a run of failures,
and a blocked run (no agent response) once per distinct reason. The first
time a job is seen, its existing files are only marked as read, so old runs are not replayed.

The Open WebUI API key (owner's account) comes from env OWUI_API_KEY. Open WebUI should limit API keys to this one
chat (Admin settings: API Key Endpoint Restrictions, Allowed Endpoints = /api/v1/chats/<chat id>). The first run, with
no chat yet, needs /api/v1/chats/new allowed once to create it; the chat id is then kept in the state file.
"""
import datetime as dt, json, os, re, sys, time, urllib.error, urllib.request, uuid
from pathlib import Path

PROFILE = Path(os.environ.get("CHESHIRE_HOME", "/home/ubuntu/.hermes/profiles/cheshire"))
JOBS = PROFILE / "cron" / "jobs.json"
OUTPUT = PROFILE / "cron" / "output"
STATE = PROFILE / "cron" / "webui-alerts-state.json"
OWUI = os.environ.get("OWUI_URL", "http://cheshire-webui.cheshire.svc.cluster.local").rstrip("/")
KEY = os.environ.get("OWUI_API_KEY", "")
MODEL = os.environ.get("OWUI_MODEL", "claude-opus-5-5")   # the model Cheshire's Open WebUI lists for her
TITLE = "Cheshire alerts"
MAX_CHARS = 8000


def api(method, path, body=None):
    req = urllib.request.Request(OWUI + path, method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def pacific(ts):
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.fromtimestamp(ts, ZoneInfo("America/Los_Angeles")).strftime("%a %b %-d, %-I:%M %p %Z")
    except Exception:
        return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def parse(doc):
    """(kind, text): ('response', agent reply) or ('problem', one-line reason) or (None, '')."""
    idx = [m.end() for m in re.finditer(r"^## Response[ \t]*$", doc, re.M)]
    if idx:
        return "response", doc[idx[-1]:].strip()
    status = re.search(r"^\*\*Status:\*\*\s*(.+)$", doc, re.M)
    reason = re.search(r"^\*\*Reason:\*\*\s*(.+)$", doc, re.M)
    if status or reason:
        return "problem", " ".join(x.group(1).strip() for x in (status, reason) if x)
    return None, ""


def message(content, parent):
    return {"id": str(uuid.uuid4()), "parentId": parent, "childrenIds": [], "role": "assistant", "content": content,
            "model": MODEL, "modelIdx": 0, "done": True, "timestamp": int(time.time())}


def linear(history):
    out, mid = [], history.get("currentId")
    while mid:
        m = history["messages"][mid]
        out.append(m)
        mid = m.get("parentId")
    return out[::-1]


def post(state, content):
    chat_id = state.get("chat_id")
    if not chat_id:
        m = message(content, None)
        hist = {"messages": {m["id"]: m}, "currentId": m["id"]}
        res = api("POST", "/api/v1/chats/new", {"chat": {"title": TITLE, "models": [MODEL], "history": hist,
                                                           "messages": [m], "timestamp": int(time.time() * 1000)}})
        state["chat_id"] = res["id"]
        print(f"created chat {res['id']} ({TITLE}); now set Allowed Endpoints to /api/v1/chats/{res['id']}")
    else:
        chat = api("GET", f"/api/v1/chats/{chat_id}")["chat"]
        hist = chat.get("history") or {"messages": {}, "currentId": None}
        parent = hist.get("currentId")
        m = message(content, parent)
        if parent in hist["messages"]:
            hist["messages"][parent].setdefault("childrenIds", []).append(m["id"])
        hist["messages"][m["id"]] = m
        hist["currentId"] = m["id"]
        api("POST", f"/api/v1/chats/{chat_id}", {"chat": {"history": hist, "messages": linear(hist)}})
    try:
        api("POST", f"/api/v1/chats/{state['chat_id']}/unread")
    except urllib.error.HTTPError:
        pass                                   # cosmetic only


def save(state):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(STATE)


def main():
    if not KEY:
        sys.exit("OWUI_API_KEY is not set")
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    seen = state.setdefault("seen", {})
    problems = state.setdefault("last_problem", {})
    raw = json.loads(JOBS.read_text())
    jobs = [j for j in (raw["jobs"] if isinstance(raw, dict) else raw) if j.get("deliver") == "local"]
    sent = 0
    if not state.get("chat_id"):               # first run: create the chat now, so its id can be locked in
        names = "\n".join(f"- {j.get('name') or j['id']}" for j in jobs) or "- (none yet)"
        post(state, "This chat collects results from my scheduled jobs. A job posts here only when it has "
                    f"something to report, or when it fails.\n\nJobs today:\n{names}\n\nYou can reply here to ask me "
                    "about any of them.")
        save(state)
    for job in jobs:
        jid, name = job["id"], job.get("name") or job["id"]
        d = OUTPUT / jid
        files = sorted(p for p in d.glob("*.md")) if d.is_dir() else []
        if jid not in seen:                    # new job: start from now, don't replay history
            seen[jid] = files[-1].name if files else ""
            continue
        for f in (p for p in files if p.name > seen[jid]):
            kind, text = parse(f.read_text(errors="replace"))
            when = pacific(f.stat().st_mtime)
            if kind == "response" and text.startswith("[CRON_FAILURE]"):
                if problems.get(jid) != "failure":   # first failure in a row only
                    problems[jid] = "failure"
                    post(state, f"**{name}**, {when}\n\n{text[len('[CRON_FAILURE]'):].strip()[:MAX_CHARS]}\n\n"
                                "(Further failures of this job stay quiet until it succeeds again.)")
                    sent += 1
            elif kind == "response" and text and not text.startswith("[SILENT]"):
                problems.pop(jid, None)
                if len(text) > MAX_CHARS:
                    text = text[:MAX_CHARS] + "\n\n…(cut; full text in Hermes cron output)"
                post(state, f"**{name}**, {when}\n\n{text}")
                sent += 1
            elif kind == "response":
                problems.pop(jid, None)
            elif kind == "problem" and problems.get(jid) != text:
                problems[jid] = text
                post(state, f"**{name}**, {when}\n\nThis scheduled job didn't run: {text}")
                sent += 1
            seen[jid] = f.name
            save(state)                        # after each post, so a later failure never re-sends this one
    save(state)
    if sent:
        print(f"forwarded {sent} result(s) to chat {state.get('chat_id')}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Benedict Wong's GitLab inbox check — read-only; it reports, it never acts.

  inbox.py            print new messages for Benedict Wong as JSON ([] = nothing new); changes nothing in GitLab
  inbox.py --mark     record everything printed by the last check as processed (run after handling it)

What counts as Benedict's inbox (as benedict-bot):
  - pending to-dos (@mentions, assignments, review requests),
  - open issues/MRs labelled "To: Benedict Wong",
  - issues/MRs benedict-bot authored, is assigned to or reviewing, or has commented on ("watched"),
    while open or closed/merged less than 3 days ago.
A message is new if someone other than benedict-bot wrote it after the last processed one. Each message carries
`trusted` (author in BENEDICT_TRUSTED) so the reader can decide what to act on.

Used by the session-scoped 10-minute watcher in Claude Code. State: ~/.local/state/benedict/.
Token: ~/.gitlab-benedict-bot (0600), never printed. Repo: turing-pi-k3/benedict/.
"""
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

STATE_DIR = Path(os.environ.get("BENEDICT_STATE", Path.home() / ".local/state/benedict"))
TOKEN_FILE = Path(os.environ.get("BENEDICT_TOKEN_FILE", Path.home() / ".gitlab-benedict-bot"))
API = os.environ.get("GITLAB_API", "http://192.168.4.201/api/v4")
HOST = os.environ.get("GITLAB_HOST", "scm.geekstyle.net")
ME, LABEL, RECENT_DAYS = "benedict-bot", "To: Benedict Wong", 3
TRUSTED = set(os.environ.get("BENEDICT_TRUSTED", "mdella,cheshire-bot,luna-bot").split(","))
SEED = ["issue:3:1", "mr:3:5", "mr:3:2"]  # threads Benedict took part in before benedict-bot existed


def token():
    for line in TOKEN_FILE.read_text().splitlines():
        if line.startswith("GITLAB_BENEDICT_BOT_TOKEN="):
            return line.split("=", 1)[1].strip()
    sys.exit(f"no token in {TOKEN_FILE}")


def get(path, **params):
    out, page = [], 1
    while True:
        url = f"{API}/{path}?{urllib.parse.urlencode(dict(params, per_page=100, page=page))}"
        req = urllib.request.Request(url, headers={"PRIVATE-TOKEN": TOKEN, "Host": HOST})
        with urllib.request.urlopen(req, timeout=60) as r:
            data, nxt = json.load(r), r.headers.get("X-Next-Page")
        if not isinstance(data, list):
            return data
        out += data
        if not nxt:
            return out
        page = int(nxt)


def endpoint(kind):
    return "issues" if kind == "issue" else "merge_requests"


def collect(state, since):
    items = {}

    def add(o, kind, why):
        k = f"{kind}:{o['project_id']}:{o['iid']}"
        items.setdefault(k, {"obj": o, "kind": kind, "why": set()})["why"].add(why)

    todos = get("todos", state="pending")
    for t in todos:
        tgt = t.get("target") or {}
        if tgt.get("iid") and t.get("target_type") in ("Issue", "WorkItem", "MergeRequest"):
            add(tgt, "mr" if t["target_type"] == "MergeRequest" else "issue", f"todo:{t['action_name']}")
    for kind in ("issue", "mr"):
        add_all = lambda objs, why: [add(o, kind, why) for o in objs]
        add_all(get(endpoint(kind), scope="all", state="opened", labels=LABEL), "label")
        roles = ("author_username", "assignee_username") + (("reviewer_username",) if kind == "mr" else ())
        for role in roles:
            add_all(get(endpoint(kind), scope="all", state="opened", **{role: ME}), role.split("_")[0])
            add_all(get(endpoint(kind), scope="all", state="closed", updated_after=since, **{role: ME}),
                    role.split("_")[0] + "-closed")
            if kind == "mr":
                add_all(get("merge_requests", scope="all", state="merged", updated_after=since, **{role: ME}),
                        role.split("_")[0] + "-merged")
    for k in list(state["watched"]):
        if k in items:
            continue
        kind, pid, iid = k.split(":")
        try:
            o = get(f"projects/{pid}/{endpoint(kind)}/{iid}")
        except Exception:
            state["watched"].remove(k)
            continue
        done = o.get("merged_at") or o.get("closed_at")
        if o["state"] != "opened" and done and done < since:
            state["watched"].remove(k)
            continue
        add(o, kind, "watched")
    return items, todos


def main():
    global TOKEN
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    sf, pf = STATE_DIR / "state.json", STATE_DIR / "pending.json"
    state = json.loads(sf.read_text()) if sf.exists() else {}
    state.setdefault("started", dt.datetime.now(dt.timezone.utc).isoformat())
    state.setdefault("seen", {})
    state.setdefault("watched", list(SEED))

    if "--mark" in sys.argv:
        if not pf.exists():
            print("nothing pending")
            return
        p = json.loads(pf.read_text())
        state["seen"].update(p["marks"])
        state["watched"] = sorted(set(state["watched"]) | set(p["watch"]))
        sf.write_text(json.dumps(state, indent=1))
        pf.unlink()
        print(f"marked {len(p['marks'])} item(s) processed")
        return

    TOKEN = token()
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=RECENT_DAYS)).isoformat()
    items, todos = collect(state, since)
    work, marks, watch = [], {}, []
    for k, it in items.items():
        o, kind = it["obj"], it["kind"]
        notes = get(f"projects/{o['project_id']}/{endpoint(kind)}/{o['iid']}/notes", sort="asc", order_by="created_at")
        mine = [n["id"] for n in notes if n["author"]["username"] == ME]
        if mine or o["author"]["username"] == ME:
            watch.append(k)
        seen = state["seen"].get(k)
        msgs = []
        if seen is None:  # first sight: start after Benedict's last message, else from now (new items: include body)
            if mine:
                seen = max(mine)
            elif o["created_at"] >= state["started"] and o["author"]["username"] != ME:
                seen = 0
                msgs.append({"id": "description", "author": o["author"]["username"], "created_at": o["created_at"],
                             "body": f"# {o['title']}\n\n{o.get('description') or ''}"})
            else:
                seen = max([n["id"] for n in notes] or [0])
        for n in notes:
            if n["id"] > seen and not n.get("system") and n["author"]["username"] != ME:
                msgs.append({"id": n["id"], "author": n["author"]["username"], "created_at": n["created_at"],
                             "body": n["body"]})
        marks[k] = max([seen] + [n["id"] for n in notes])
        if msgs:
            for m in msgs:
                m["trusted"] = m["author"] in TRUSTED
            work.append({"key": k, "type": kind, "project_id": o["project_id"], "iid": o["iid"],
                         "title": o["title"], "state": o["state"], "url": o["web_url"],
                         "labels": o.get("labels", []), "why": sorted(it["why"]), "messages": msgs,
                         "todo_ids": [t["id"] for t in todos if (t.get("target") or {}).get("iid") == o["iid"]
                                      and (t.get("target") or {}).get("project_id") == o["project_id"]]})
    if work:
        pf.write_text(json.dumps({"marks": marks, "watch": watch}))
    else:  # nothing to handle: advance the baseline right away
        state["seen"].update(marks)
        state["watched"] = sorted(set(state["watched"]) | set(watch))
    sf.write_text(json.dumps(state, indent=1))
    print(json.dumps(work, indent=1))


if __name__ == "__main__":
    main()

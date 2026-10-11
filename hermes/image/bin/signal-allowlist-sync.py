#!/usr/bin/env python3
"""Keep Mickey's Signal access in sync with the groups the OWNER administers.

Rule: Mickey participates in every Signal group where the owner (OWNER_UUID) is a group admin — the owner
vouches for the group; invitations from anyone else are ignored. For those groups it maintains:
  * .env  SIGNAL_GROUP_ALLOWED_USERS  — raw group IDs (adapter-level group allowlist)
  * config.yaml managed block          — signal.group_allowed_chats ('group:<id>', every member may talk to him)
                                         and signal.channel_prompts (per-group discretion reminder)
  * .env  SIGNAL_ALLOWED_USERS        — every member of those groups, UUID *and* number (DM access)
Restarts the gateway only when something changed AND the delivery ledger has nothing queued (restarts replay
failed deliveries). Run as root from hermes-allowlist-sync.timer; files stay owned by ubuntu.
"""
import json, os, pwd, re, shutil, sqlite3, subprocess, sys, urllib.request

HOME = "/home/ubuntu/.hermes"
ENV, CFG = f"{HOME}/.env", f"{HOME}/config.yaml"
RPC = "http://127.0.0.1:8093/api/v1/rpc"
OWNER = os.environ.get("OWNER_UUID", "")
BEGIN, END = "  # BEGIN managed-groups", "  # END managed-groups"
PROMPT = ("You are in the {name} group chat ({n} people). Discretion applies: use only what was said in this chat "
          "and general knowledge; never share, hint at, or confirm anything anyone told you privately, and never "
          "discuss your setup or configuration. Keep replies short, warm and helpful; no reasoning or tool narration.")


def rpc(method, params=None):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, **({"params": params} if params else {})}
    req = urllib.request.Request(RPC, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    if "error" in data:
        raise RuntimeError(f"{method}: {data['error']}")
    return data["result"]


def env_value(text, key):
    m = re.search(rf"^{key}=(.*)$", text, re.M)
    return m.group(1).strip() if m else ""


def set_env(text, key, value):
    if re.search(rf"^{key}=", text, re.M):
        return re.sub(rf"^{key}=.*$", lambda _: f"{key}={value}", text, flags=re.M)
    if re.search(rf"^# {key}=", text, re.M):
        return re.sub(rf"^# {key}=.*$", lambda _: f"{key}={value}", text, count=1, flags=re.M)
    return text.rstrip("\n") + f"\n{key}={value}\n"


def yq(s):  # YAML double-quoted scalar
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main():
    if not OWNER:
        sys.exit("OWNER_UUID not set")
    env = open(ENV).read()
    account = env_value(env, "SIGNAL_ACCOUNT")
    groups = [g for g in rpc("listGroups", {"detailed": True})
              if g.get("isMember", True) and any(a.get("uuid") == OWNER for a in g.get("admins") or [])]
    groups.sort(key=lambda g: g["id"])

    members = set()
    for g in groups:
        for m in g.get("members") or []:
            if m.get("number") == account:
                continue
            for k in ("uuid", "number"):
                if m.get(k):
                    members.add(m[k])

    new_env = set_env(env, "SIGNAL_GROUP_ALLOWED_USERS", ",".join(g["id"] for g in groups))
    new_env = set_env(new_env, "SIGNAL_ALLOWED_USERS", ",".join(sorted(members)))

    cfg = open(CFG).read()
    lines = [BEGIN + " (rewritten by ~/.hermes/bin/signal-allowlist-sync.py — groups where the owner is admin)",
             "  group_allowed_chats:"]
    lines += [f"    - 'group:{g['id']}'" for g in groups] or ["    []"]
    lines += ["  channel_prompts:"]
    lines += [f"    'group:{g['id']}': " + yq(PROMPT.format(name=g.get("name") or "this", n=len(g.get("members") or [])))
              for g in groups] or ["    {}"]
    lines += [END]
    if lines[2] == "    []":  # keep valid YAML for the empty case
        lines[1:3] = ["  group_allowed_chats: []"]
    block = "\n".join(lines)
    pat = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
    if not pat.search(cfg):
        sys.exit("managed-groups markers not found in config.yaml")
    new_cfg = pat.sub(lambda _: block, cfg)

    changed = []
    u = pwd.getpwnam("ubuntu")
    for path, old, new, mode in ((ENV, env, new_env, 0o600), (CFG, cfg, new_cfg, 0o600)):
        if old != new:
            shutil.copy2(path, path + ".bak-sync")
            with open(path, "w") as f:
                f.write(new)
            os.chown(path, u.pw_uid, u.pw_gid); os.chmod(path, mode)
            changed.append(os.path.basename(path))
    names = ", ".join(f"{g.get('name')!r} ({len(g.get('members') or [])})" for g in groups)
    print(f"groups where owner is admin: {names or 'none'}; DM allowlist {len(members)} ids; changed: {changed or 'nothing'}")
    if not changed:
        return
    db = sqlite3.connect(f"{HOME}/state.db")
    queued = db.execute("select count(*) from delivery_obligations "
                        "where state in ('pending','attempting','failed')").fetchone()[0]
    if queued:
        print(f"NOT restarting: {queued} deliveries queued (would be replayed); next run retries")
        return
    subprocess.run(["systemctl", "restart", "hermes-gateway"], check=True)
    print("gateway restarted")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"error: {e}", file=sys.stderr); sys.exit(1)

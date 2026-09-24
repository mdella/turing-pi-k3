#!/usr/bin/env python3
"""Sync SIGNAL_ALLOWED_USERS in ~/.hermes/.env with the members of the allowed Signal groups.

Anyone in an allowed group may DM Mickey (chat-only tools apply on Signal). Signal senders arrive as a
phone number *or* a UUID and Hermes only matches the primary id, so both forms are listed. Restarts the
gateway only when the list changed AND the delivery ledger has nothing queued (a restart replays failed
deliveries). Run as root (systemd timer); files stay owned by ubuntu.
"""
import json, os, pwd, re, shutil, sqlite3, subprocess, sys, time, urllib.request

HOME = "/home/ubuntu/.hermes"
ENV = f"{HOME}/.env"
RPC = "http://127.0.0.1:8093/api/v1/rpc"


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


def main():
    text = open(ENV).read()
    account = env_value(text, "SIGNAL_ACCOUNT")
    groups = {g for g in env_value(text, "SIGNAL_GROUP_ALLOWED_USERS").split(",") if g}
    if not groups:
        print("no allowed groups; nothing to do"); return
    ids = set()
    for g in rpc("listGroups", {"detailed": True}):
        if g.get("id") not in groups:
            continue
        for m in g.get("members") or []:
            if m.get("number") == account:
                continue  # the bot itself
            for k in ("uuid", "number"):
                if m.get(k):
                    ids.add(m[k])
    new = ",".join(sorted(ids))
    old = env_value(text, "SIGNAL_ALLOWED_USERS")
    if new == old:
        print(f"allowlist unchanged ({len(ids)} ids)"); return
    backup = f"{ENV}.bak-allowlist"
    shutil.copy2(ENV, backup)
    if re.search(r"^SIGNAL_ALLOWED_USERS=", text, re.M):
        text = re.sub(r"^SIGNAL_ALLOWED_USERS=.*$", f"SIGNAL_ALLOWED_USERS={new}", text, flags=re.M)
    else:
        text = re.sub(r"^# SIGNAL_ALLOWED_USERS=.*$", f"SIGNAL_ALLOWED_USERS={new}", text, flags=re.M) \
            if re.search(r"^# SIGNAL_ALLOWED_USERS=", text, re.M) else text.rstrip("\n") + f"\nSIGNAL_ALLOWED_USERS={new}\n"
    with open(ENV, "w") as f:
        f.write(text)
    u = pwd.getpwnam("ubuntu"); os.chown(ENV, u.pw_uid, u.pw_gid); os.chmod(ENV, 0o600)
    print(f"allowlist updated: {len(old.split(',')) if old else 0} -> {len(ids)} ids")
    db = sqlite3.connect(f"{HOME}/state.db")
    queued = db.execute("select count(*) from delivery_obligations where state in ('pending','attempting','failed')").fetchone()[0]
    if queued:
        print(f"NOT restarting: {queued} deliveries queued (would be replayed); next run retries"); return
    subprocess.run(["systemctl", "restart", "hermes-gateway"], check=True)
    print("gateway restarted")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"error: {e}", file=sys.stderr); sys.exit(1)

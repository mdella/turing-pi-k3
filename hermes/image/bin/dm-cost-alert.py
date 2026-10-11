#!/usr/bin/env python3
"""Alert the owner (Signal DM from Mickey's number) when Signal *DM* spend gets expensive.

Reads Hermes' own per-session estimates (state.db: sessions.chat_type='dm', session_model_usage).
Thresholds: today (UTC) and last 30 days. Each threshold alerts at most once per day (state file).
Owner = first SIGNAL owner UUID below. Sends via signal-cli JSON-RPC, not through the agent.
"""
import datetime as dt, json, os, sqlite3, urllib.request

HOME = "/home/ubuntu/.hermes"
OWNER = os.environ.get("ALERT_TO", "")            # set in the systemd unit (owner's Signal UUID)
DAY_LIMIT = float(os.environ.get("DM_DAY_USD", "5"))
MONTH_LIMIT = float(os.environ.get("DM_30D_USD", "30"))
STATE = f"{HOME}/.dm-cost-alert.json"
RPC = "http://127.0.0.1:8093/api/v1/rpc"


def spend(since_ts):
    db = sqlite3.connect(f"{HOME}/state.db")
    rows = db.execute(
        """select coalesce(s.user_id,'?'), sum(u.estimated_cost_usd), sum(u.api_call_count)
           from session_model_usage u join sessions s on s.id = u.session_id
           where s.source = 'signal' and s.chat_type = 'dm' and u.last_seen >= ?
           group by 1 order by 2 desc""", (since_ts,)).fetchall()
    return sum(r[1] or 0 for r in rows), rows


def names():
    try:
        req = urllib.request.Request(RPC, json.dumps({"jsonrpc": "2.0", "id": 1, "method": "listContacts",
                                     "params": {"allRecipients": True, "detailed": True}}).encode(),
                                     {"Content-Type": "application/json"})
        res = json.load(urllib.request.urlopen(req, timeout=30)).get("result", [])
        out = {}
        for c in res:
            p = c.get("profile") or {}
            n = " ".join(x for x in (p.get("givenName"), p.get("familyName")) if x) or c.get("name") or ""
            for k in ("uuid", "number"):
                if c.get(k) and n:
                    out[c[k]] = n
        return out
    except Exception:
        return {}


def send(text):
    body = {"jsonrpc": "2.0", "id": 1, "method": "send", "params": {"recipient": [OWNER], "message": text}}
    req = urllib.request.Request(RPC, json.dumps(body).encode(), {"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=60).read()


def main():
    now = dt.datetime.now(dt.UTC)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_total, day_rows = spend(today.timestamp())
    m_total, _ = spend((now - dt.timedelta(days=30)).timestamp())
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    key = today.strftime("%Y-%m-%d")
    alerts = []
    if day_total >= DAY_LIMIT and state.get("day") != key:
        alerts.append(("day", f"today ${day_total:.2f} (limit ${DAY_LIMIT:.0f}/day)"))
    if m_total >= MONTH_LIMIT and state.get("month") != key:
        alerts.append(("month", f"last 30 days ${m_total:.2f} (limit ${MONTH_LIMIT:.0f})"))
    print(f"DM spend: today ${day_total:.3f}, 30d ${m_total:.3f}; alerts: {[a[0] for a in alerts]}")
    if not alerts or not OWNER:
        return
    who = names()
    top = ", ".join(f"{who.get(u, u[:8])} ${c:.2f} ({n} replies)" for u, c, n in day_rows[:5]) or "n/a"
    send("💸 Mickey cost alert — private DMs: " + "; ".join(a[1] for a in alerts) +
         f".\nToday's top DM users: {top}.\n(Group chat not included. Long DM conversations cost the most.)")
    for kind, _ in alerts:
        state[kind] = key
    json.dump(state, open(STATE, "w"))


if __name__ == "__main__":
    main()

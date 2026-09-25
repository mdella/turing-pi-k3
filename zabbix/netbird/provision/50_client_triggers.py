"""
50_client_triggers.py

Step 5: client-side triggers, dependent on the server-side 'metrics endpoint unreachable' trigger.

Idempotent: existing items/triggers/macros are left as they are (macros are updated).
Run from this folder: uv run --no-project --python 3.12 50_client_triggers.py
"""
from zbx import api
HID, K = "10788", "/netbird.cstone.com/"
TAGS = [{"tag": "component", "value": "netbird"}, {"tag": "source", "value": "mac-studio-client"}]
have = {t["description"]: t["triggerid"] for t in api("trigger.get", {"hostids": [HID], "output": ["description"]})}
def trig(desc, expr, prio, comments, deps=()):
    if desc in have: return have[desc]
    p = {"description": desc, "expression": expr, "priority": prio, "comments": comments, "tags": TAGS}
    if deps: p["dependencies"] = [{"triggerid": have[d]} for d in deps]
    have[desc] = api("trigger.create", p)["triggerids"][0]; return have[desc]
SERVER_DOWN = "NetBird: metrics endpoint unreachable (management server down?)"
trig("NetBird client (Mac Studio): check not reporting", f"nodata({K}netbird.client.management,10m)=1", 3,
     "No values from netbird_zabbix_status.py for 10 min. Check: sudo launchctl print system/com.mdella.netbird-zabbix; ~/Library/Logs/netbird-zabbix.log on the Mac.")
trig("NetBird client (Mac Studio): cannot reach management", f"max({K}netbird.client.management,3m)=0", 4,
     "The Mac's netbird client has not been connected to management for 3 checks. Error text: item 'NetBird client (Mac Studio): errors'.",
     deps=[SERVER_DOWN, "NetBird client (Mac Studio): check not reporting"])
trig("NetBird client (Mac Studio): signal disconnected", f"max({K}netbird.client.signal,3m)=0", 4,
     "The Mac's netbird client has not been connected to signal for 3 checks: new peer connections can't be set up.",
     deps=[SERVER_DOWN, "NetBird client (Mac Studio): cannot reach management"])
trig("NetBird client (Mac Studio): relay/STUN endpoint unavailable", f"max({K}netbird.client.relays.available,10m)<last({K}netbird.client.relays.total)", 2,
     "At least one relay/STUN endpoint (stun:netbird.cstone.com:3478 or rels://netbird.cstone.com:443) unreachable from the Mac for 10 min.",
     deps=["NetBird client (Mac Studio): cannot reach management"])
trig("NetBird client (Mac Studio): fewer than {$NETBIRD.PEERS.MIN} peers connected", f"max({K}netbird.client.peers.connected,15m)<{{$NETBIRD.PEERS.MIN}}", 2,
     "The Mac sees fewer connected peers than expected. Names in item 'NetBird client (Mac Studio): peers not connected'.",
     deps=["NetBird client (Mac Studio): cannot reach management"])
for t in api("trigger.get", {"hostids": [HID], "output": ["description", "value", "state", "error"], "search": {"description": "NetBird client"}}):
    print(f"  {'PROBLEM' if t['value']=='1' else 'ok':7} {t['description']} {('ERR '+t['error']) if t['state']=='1' else ''}")

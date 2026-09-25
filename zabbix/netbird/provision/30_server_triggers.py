"""
30_server_triggers.py

Step 3: server-side triggers (metrics unreachable, no/low peers, 5xx, IP changed, 4x container not running).

Idempotent: existing items/triggers/macros are left as they are (macros are updated).
Run from this folder: uv run --no-project --python 3.12 30_server_triggers.py
"""
from zbx import api
HID, H = "10788", "netbird.cstone.com"
TAGS = [{"tag": "component", "value": "netbird"}]
have = {t["description"] for t in api("trigger.get", {"hostids": [HID], "output": ["description"]})}
made = {}
def trig(desc, expr, prio, comments, deps=()):
    if desc in have: return
    p = {"description": desc, "expression": expr, "priority": prio, "comments": comments, "tags": TAGS, "manual_close": 0}
    if deps: p["dependencies"] = [{"triggerid": made[d]} for d in deps if d in made]
    made[desc] = api("trigger.create", p)["triggerids"][0]
K = f"/{H}/"
trig("NetBird: metrics endpoint unreachable (management server down?)", f"nodata({K}netbird.signal.peers,5m)=1", 4,
     "No metrics from netbird-server for 5 min. The server process is down or hung, or the container IP changed (see the IP trigger).")
trig("NetBird: no peers connected to signal", f"max({K}netbird.signal.peers,10m)=0", 4,
     "Metrics are arriving but no peer has been connected to signal for 10 min: peers can't set up connections.",
     deps=["NetBird: metrics endpoint unreachable (management server down?)"])
trig("NetBird: fewer than {$NETBIRD.PEERS.MIN} peers connected", f"max({K}netbird.signal.peers,15m)<{{$NETBIRD.PEERS.MIN}} or max({K}netbird.mgmt.streams,15m)<{{$NETBIRD.PEERS.MIN}}", 2,
     "Normally ~8 peers are connected. A drop suggests clients can't reach management/signal.",
     deps=["NetBird: no peers connected to signal"])
trig("NetBird: management API returning 5xx errors", f"avg({K}netbird.mgmt.http5xx.rate,10m)>0.01", 2,
     "Sustained HTTP 5xx from the management API over 10 min.")
trig("NetBird: server container IP changed, metrics macro is stale", f'last({K}netbird.server.ip)<>"{{$NETBIRD.METRICS.IP}}"', 3,
     "netbird-server got a new docker IP (container recreated). Update host macro {$NETBIRD.METRICS.IP} to the value of 'NetBird: server container IP'. A static IP in the droplet's compose file avoids this.")
for c in ["netbird-server", "netbird-traefik", "netbird-dashboard", "netbird-proxy"]:
    k = f'docker.container_info.state.running["/{c}"]'
    trig(f"NetBird: container {c} is not running", f"last({K}{k})=0 or nodata({K}{k},15m)=1", 4,
         f"Docker reports /{c} not running, or no state for 15 min (container removed/renamed). The Docker template only alerts on error exits and failed health checks, and these containers have no health check.")
print("triggers created:", len(made), list(made))
# collect now instead of waiting for the first interval
ids = [i["itemid"] for i in api("item.get", {"hostids": [HID], "output": ["itemid"], "filter": {"key_": ["web.page.get[{$NETBIRD.METRICS.IP},/metrics,{$NETBIRD.METRICS.PORT}]", "docker.container_info[netbird-server,full]"]}})]
api("task.create", [{"type": 6, "request": {"itemid": i}} for i in ids]); print("collection triggered for", len(ids), "master items")

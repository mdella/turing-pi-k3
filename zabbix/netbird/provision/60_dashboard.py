"""
60_dashboard.py

Step 6: 'NetBird health' dashboard (public). Needs item ids: runs the lookup itself.

Idempotent: existing items/triggers/macros are left as they are (macros are updated).
Run from this folder: uv run --no-project --python 3.12 60_dashboard.py
"""
from zbx import api
KEYS = ["netbird.signal.peers", "netbird.relay.peers", "netbird.mgmt.streams", "netbird.mgmt.http5xx.rate", "netbird.mgmt.sync.rate",
        "netbird.relay.reconnect.rate", "netbird.client.management", "netbird.client.signal", "netbird.client.relays.available",
        "netbird.client.peers.connected", "netbird.client.peers.down", "netbird.client.errors", "netbird.client.version"] + \
       [f'docker.container_info.state.running["/netbird-{c}"]' for c in ("server", "traefik", "dashboard", "proxy")]
ids = {i["key_"]: i["itemid"] for i in api("item.get", {"hostids": ["10788"], "output": ["itemid", "key_"], "filter": {"key_": KEYS}})}
missing = [k for k in KEYS if k not in ids]
assert not missing, f"run steps 2-5 first; missing items: {missing}"
RED, AMBER, GREEN, GREY = "E57373", "FFB74D", "81C784", "B0BEC5"
def F(t, n, v): return {"type": t, "name": n, "value": v}
def tile(name, key, x, y, w=9, h=2, thresholds=(), spark=True, label=None, text=False):
    # Header hidden (view_mode 1): a narrow tile truncates it ("Server: signal ..."). The label is shown inside,
    # centred and bold, above a centred value. aggregate_function MUST be 0 (current value): the API otherwise
    # stores 2 (= max over a period), which keeps a status tile green during an outage and, without a
    # time period, makes the frontend report "Widget is not fully configured".
    f = [F(4, "itemid.0", ids[key]), F(0, "show.0", 1), F(0, "show.1", 2),
         F(1, "description", label or name), F(0, "desc_size", 12 if text else 17), F(0, "desc_bold", 1),
         F(0, "desc_h_pos", 1), F(0, "desc_v_pos", 0), F(0, "value_size", 16 if text else 40),
         F(0, "value_h_pos", 1), F(0, "value_v_pos", 1), F(0, "units_show", 1), F(0, "aggregate_function", 0)]
    if spark: f += [F(0, "show.2", 5), F(0, "sparkline.width", 1), F(0, "sparkline.fill", 2)]
    for i, (c, t) in enumerate(thresholds):
        f += [F(1, f"thresholds.{i}.color", c), F(1, f"thresholds.{i}.threshold", str(t))]
    return {"type": "item", "name": name, "x": x, "y": y, "width": w, "height": h, "view_mode": 1, "fields": f}
BOOL = [(RED, 0), (GREEN, 1)]
PEERS = [(RED, 0), (AMBER, 1), (GREEN, 3)]
def graph(name, x, y, w, h, series):
    f = [F(1, "time_period.from", "now-6h"), F(1, "time_period.to", "now"), F(0, "legend", 1)]
    for i, (key, color) in enumerate(series):
        f += [F(0, f"ds.{i}.dataset_type", 0), F(4, f"ds.{i}.itemids.0", ids[key]), F(1, f"ds.{i}.color.0", color),
              F(0, f"ds.{i}.type", 0), F(0, f"ds.{i}.width", 2), F(0, f"ds.{i}.fill", 1)]
    return {"type": "svggraph", "name": name, "x": x, "y": y, "width": w, "height": h, "view_mode": 0, "fields": f}
W = []
# row 1: headline health (server side | Mac client side)
W += [tile("Server: signal peers", "netbird.signal.peers", 0, 0, label="Server\nsignal peers", thresholds=PEERS),
      tile("Server: relay peers", "netbird.relay.peers", 9, 0, label="Server\nrelay peers", thresholds=PEERS),
      tile("Server: management streams", "netbird.mgmt.streams", 18, 0, label="Server\nmgmt streams", thresholds=PEERS),
      tile("Server: API 5xx /s", "netbird.mgmt.http5xx.rate", 27, 0, label="Server\nAPI 5xx /s", thresholds=[(GREEN, 0), (RED, 0.01)]),
      tile("Mac client: management", "netbird.client.management", 36, 0, label="Mac client\nmanagement", thresholds=BOOL),
      tile("Mac client: signal", "netbird.client.signal", 45, 0, label="Mac client\nsignal", thresholds=BOOL),
      tile("Mac client: relays available", "netbird.client.relays.available", 54, 0, label="Mac client\nrelays up", thresholds=[(RED, 0), (AMBER, 1), (GREEN, 2)]),
      tile("Mac client: peers connected", "netbird.client.peers.connected", 63, 0, label="Mac client\npeers connected", thresholds=PEERS)]
# row 2: containers + context
for i, c in enumerate(("server", "traefik", "dashboard", "proxy")):
    W.append(tile(f"netbird-{c} running", f'docker.container_info.state.running["/netbird-{c}"]', 9 * i, 2, thresholds=BOOL, spark=False, label=f"container\nnetbird-{c}"))
W += [tile("Mac client: peers not connected", "netbird.client.peers.down", 36, 2, w=24, spark=False, text=True),
      tile("Client version", "netbird.client.version", 60, 2, w=12, spark=False, label="NetBird client version", text=True)]
# row 3: history
W += [graph("Connected peers (server vs Mac client view)", 0, 4, 36, 5,
            [("netbird.signal.peers", "42A5F5"), ("netbird.relay.peers", "AB47BC"), ("netbird.mgmt.streams", "26A69A"), ("netbird.client.peers.connected", "FFA726")]),
      graph("Management activity & errors (per second)", 36, 4, 36, 5,
            [("netbird.mgmt.sync.rate", "42A5F5"), ("netbird.relay.reconnect.rate", "FFA726"), ("netbird.mgmt.http5xx.rate", "E53935")])]
# row 4: problems + client errors
W += [{"type": "problems", "name": "NetBird problems", "x": 0, "y": 9, "width": 48, "height": 5, "view_mode": 0,
       "fields": [F(3, "hostids.0", "10788"), F(1, "tags.0.tag", "component"), F(0, "tags.0.operator", 1), F(1, "tags.0.value", "netbird"),
                  F(0, "show", 3), F(0, "show_tags", 1)]},
      tile("Mac client: errors (empty = healthy)", "netbird.client.errors", 48, 9, w=24, h=5, spark=False, text=True)]
existing = api("dashboard.get", {"output": ["dashboardid"], "filter": {"name": "NetBird health"}})
body = {"name": "NetBird health", "display_period": 30, "auto_start": 1, "private": 0,
        "pages": [{"name": "", "widgets": W}]}
if existing:
    body["dashboardid"] = existing[0]["dashboardid"]; api("dashboard.update", body); did = existing[0]["dashboardid"]
else:
    did = api("dashboard.create", body)["dashboardids"][0]
d = api("dashboard.get", {"dashboardids": [did], "output": ["name", "private"], "selectPages": "extend"})[0]
print("dashboard", did, d["name"], "| public" if d["private"] == "0" else "| private", "| widgets:", len(d["pages"][0]["widgets"]))

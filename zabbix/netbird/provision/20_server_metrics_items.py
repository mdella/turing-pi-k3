"""
20_server_metrics_items.py

Step 2: server-side NetBird health: macros, raw /metrics master item (read by the droplet's agent2 from the
netbird-server container), Prometheus-preprocessed dependent items, container-IP self-check.

Idempotent: existing items/triggers/macros are left as they are (macros are updated).
Run from this folder: uv run --no-project --python 3.12 20_server_metrics_items.py
"""
from zbx import api
HID, H = "10788", "netbird.cstone.com"
iface = next(i["interfaceid"] for i in api("hostinterface.get", {"hostids": [HID], "output": ["interfaceid", "main", "type"]}) if i["main"] == "1" and i["type"] == "1")
existing = {i["key_"] for i in api("item.get", {"hostids": [HID], "output": ["key_"], "search": {"key_": "netbird."}})}
TAG = [{"tag": "component", "value": "netbird"}]

# 1. macros (create or update)
cur = {m["macro"]: m for m in api("usermacro.get", {"hostids": [HID], "output": ["hostmacroid", "macro", "value"]})}
for mac, val, desc in [("{$NETBIRD.METRICS.IP}", "172.30.0.3", "netbird-server container IP on the droplet's docker network (see trigger 'metrics IP changed')"),
                       ("{$NETBIRD.METRICS.PORT}", "9090", "netbird-server Prometheus metrics port (not published; reached from the droplet host)"),
                       ("{$NETBIRD.PEERS.MIN}", "3", "minimum expected connected peers (signal / management streams)")]:
    if mac in cur: api("usermacro.update", {"hostmacroid": cur[mac]["hostmacroid"], "value": val, "description": desc})
    else: api("usermacro.create", {"hostid": HID, "macro": mac, "value": val, "description": desc})

def mk(params):
    if params["key_"] in existing: return next(i["itemid"] for i in api("item.get", {"hostids": [HID], "output": ["itemid"], "filter": {"key_": params["key_"]}}))
    params.update({"hostid": HID, "tags": TAG}); return api("item.create", params)["itemids"][0]

# 2. master: raw /metrics via the droplet's agent2 (history 0 = not stored)
master = mk({"name": "NetBird: metrics (raw)", "key_": "web.page.get[{$NETBIRD.METRICS.IP},/metrics,{$NETBIRD.METRICS.PORT}]", "type": 0, "value_type": 4,
             "interfaceid": iface, "delay": "1m", "history": "0", "trends": "0", "timeout": "15s",
             "description": "Prometheus exposition of the combined netbird-server (management, signal, relay). Master for NetBird: items.",
             "preprocessing": [{"type": 21, "params": "var i = value.indexOf('\\r\\n\\r\\n'); if (i < 0) throw 'no HTTP body'; var s = value.substring(0, 20); if (s.indexOf(' 200') < 0) throw 'HTTP status: ' + s; return value.substring(i + 4);", "error_handler": 0, "error_handler_params": ""}]})
def prom(name, key, pattern, how="value", fn="", vt=3, units="", rate=False, onfail0=False, desc=""):
    pp = [{"type": 22, "params": f"{pattern}\n{how}\n{fn}", "error_handler": 2 if onfail0 else 0, "error_handler_params": "0" if onfail0 else ""}]
    if rate: pp.append({"type": 10, "params": "", "error_handler": 0, "error_handler_params": ""})
    return mk({"name": name, "key_": key, "type": 18, "master_itemid": master, "value_type": vt, "units": units, "preprocessing": pp, "description": desc})
prom("NetBird: signal connected peers", "netbird.signal.peers", "signal_active_peers", desc="Peers connected to the signal service (needed to set up peer-to-peer connections).")
prom("NetBird: relay peers", "netbird.relay.peers", "relay_peers", "function", "sum", desc="Peers connected to the relay (all transports).")
prom("NetBird: management connected streams", "netbird.mgmt.streams", "management_grpc_connected_streams_ratio", vt=0, desc="Open management gRPC sync streams (≈ connected clients).")
prom("NetBird: management 5xx responses per second", "netbird.mgmt.http5xx.rate", 'management_http_response_counter_code_total{code=~"5.."}', "function", "sum", vt=0, units="rps", rate=True, onfail0=True, desc="0 when no 5xx has ever been returned.")
prom("NetBird: management sync requests per second", "netbird.mgmt.sync.rate", "management_grpc_sync_request_counter_total", vt=0, units="rps", rate=True, onfail0=True)
prom("NetBird: relay reconnections per second", "netbird.relay.reconnect.rate", "relay_peer_reconnections_total", vt=0, units="rps", rate=True, onfail0=True, desc="0 until the first reconnection after a server restart (the counter is absent until then).")

# 3. container IP self-check (the macro above is a docker-internal IP that changes if the container is recreated)
info = mk({"name": "NetBird: server container info (raw)", "key_": "docker.container_info[netbird-server,full]", "type": 0, "value_type": 4, "interfaceid": iface,
           "delay": "5m", "history": "0", "trends": "0", "tags": TAG})
mk({"name": "NetBird: server container IP", "key_": "netbird.server.ip", "type": 18, "master_itemid": info, "value_type": 1, "trends": "0",
    "preprocessing": [{"type": 12, "params": "$.NetworkSettings.Networks.*.IPAddress.first()", "error_handler": 0, "error_handler_params": ""}]})
print("items:", sorted(i["key_"] for i in api("item.get", {"hostids": [HID], "output": ["key_"], "tags": [{"tag": "component", "value": "netbird", "operator": 1}]})))

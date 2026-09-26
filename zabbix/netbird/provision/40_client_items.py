"""
40_client_items.py

Step 4: trapper items netbird.client.* fed by ../netbird_zabbix_status.py on the Mac Studio.

Idempotent: existing items/triggers/macros are left as they are (macros are updated).
Run from this folder: uv run --no-project --python 3.12 40_client_items.py
"""
from zbx import api
HID = "10788"
TAGS = [{"tag": "component", "value": "netbird"}, {"tag": "source", "value": "mac-studio-client"}]
have = {i["key_"] for i in api("item.get", {"hostids": [HID], "output": ["key_"], "search": {"key_": "netbird.client."}})}
P = "NetBird client (Mac Studio): "
defs = [
    ("netbird.client.daemon", "daemon connected", 3, "", "1 = local netbird daemon reports Connected"),
    ("netbird.client.management", "management connected", 3, "", "1 = client is connected to the management service"),
    ("netbird.client.signal", "signal connected", 3, "", "1 = client is connected to the signal service"),
    ("netbird.client.relays.available", "relays available", 3, "", "STUN + relay endpoints the client can reach"),
    ("netbird.client.relays.total", "relays total", 3, "", ""),
    ("netbird.client.peers.connected", "peers connected", 3, "", ""),
    ("netbird.client.peers.total", "peers total", 3, "", ""),
    ("netbird.client.peers.p2p", "peers direct (P2P)", 3, "", "connected peers using a direct WireGuard path"),
    ("netbird.client.peers.relayed", "peers relayed", 3, "", "connected peers going through the relay"),
    ("netbird.client.version", "daemon version", 1, "", ""),
    ("netbird.client.errors", "errors", 4, "", "management/signal/relay error strings reported by the client ('' when healthy)"),
    ("netbird.client.peers.down", "peers not connected", 4, "", "names of peers not in Connected state"),
    ("netbird.client.peers.up", "peers connected", 4, "", "names of connected peers with connection type (P2P = direct, Relayed = via the relay)"),
]
for key, name, vt, units, desc in defs:
    if key in have: continue
    api("item.create", {"hostid": HID, "name": P + name, "key_": key, "type": 2, "value_type": vt, "units": units,
                        "description": desc + (" | pushed every 60 s by netbird_zabbix_status.py (LaunchDaemon com.mdella.netbird-zabbix on the Mac Studio)" if desc else "pushed every 60 s by netbird_zabbix_status.py"),
                        "history": "30d", "trends": "365d" if vt in (0, 3) else "0", "tags": TAGS})
print("client items:", sorted(i["key_"] for i in api("item.get", {"hostids": [HID], "output": ["key_"], "search": {"key_": "netbird.client."}})))

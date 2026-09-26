#!/usr/bin/env python3
"""
netbird_zabbix_status.py: client-side NetBird health check for Zabbix.

Runs on the Mac Studio (a NetBird peer) every 60 s via the system LaunchDaemon
com.mdella.netbird-zabbix. Reads `netbird status --json` and pushes the client's view of the NetBird
service (management/signal connectivity, relay reachability, peer counts) with zabbix_sender to the
trapper items netbird.client.* on Zabbix host "netbird.cstone.com".

This complements the server-side checks (netbird-server Prometheus metrics read on the droplet): those
show the server is up; this shows a real client can actually use it.

Exit codes: 0 = all values accepted by Zabbix; 1 = netbird CLI failed; 2 = zabbix_sender rejected values.
"""
import json, subprocess, sys

NETBIRD = "/usr/local/bin/netbird"
SENDER = "/opt/homebrew/bin/zabbix_sender"
ZBX_SERVER, ZBX_PORT, ZBX_HOST = "127.0.0.1", "10051", "netbird.cstone.com"


def main() -> int:
    try:
        raw = subprocess.run([NETBIRD, "status", "--json"], capture_output=True, text=True, timeout=30)
        st = json.loads(raw.stdout)
    except Exception as e:  # daemon down / CLI missing: report it as "everything down" instead of going silent
        print(f"netbird status failed: {e}", file=sys.stderr)
        st = {"daemonStatus": "Unavailable", "management": {"connected": False, "error": f"netbird status failed: {e}"},
              "signal": {"connected": False}, "relays": {}, "peers": {}}
    mgmt, sig, rel, peers = st.get("management", {}), st.get("signal", {}), st.get("relays", {}), st.get("peers", {})
    details = peers.get("details", []) or []
    connected = [p for p in details if p.get("status") == "Connected"]
    errors = [f"management: {mgmt['error']}" for _ in [0] if mgmt.get("error")] + \
             [f"signal: {sig['error']}" for _ in [0] if sig.get("error")] + \
             [f"relay {r.get('uri')}: {r.get('error')}" for r in rel.get("details", []) or [] if r.get("error")]
    values = {
        "netbird.client.daemon": int(st.get("daemonStatus") == "Connected"),
        "netbird.client.management": int(bool(mgmt.get("connected"))),
        "netbird.client.signal": int(bool(sig.get("connected"))),
        "netbird.client.relays.available": rel.get("available", 0),
        "netbird.client.relays.total": rel.get("total", 0),
        "netbird.client.peers.connected": peers.get("connected", len(connected)),
        "netbird.client.peers.total": peers.get("total", len(details)),
        "netbird.client.peers.p2p": sum(1 for p in connected if p.get("connectionType") == "P2P"),
        "netbird.client.peers.relayed": sum(1 for p in connected if p.get("connectionType") == "Relayed"),
        "netbird.client.version": st.get("daemonVersion", "unknown"),
        "netbird.client.errors": "; ".join(errors),
        "netbird.client.peers.up": ", ".join(sorted(p.get("fqdn", "?").split(".")[0] + f" ({p.get('connectionType', '?')})"
                                                    for p in connected)),
        "netbird.client.peers.down": ", ".join(sorted(p.get("fqdn", "?").split(".")[0] + f" ({p.get('status')})"
                                                      for p in details if p.get("status") != "Connected")),
    }
    # zabbix_sender input: <host> <key> <value>, one per line; quote values (they may contain spaces)
    lines = "".join(f'"{ZBX_HOST}" {k} {json.dumps(str(v))}\n' for k, v in values.items())
    out = subprocess.run([SENDER, "-z", ZBX_SERVER, "-p", ZBX_PORT, "-i", "-"], input=lines, capture_output=True, text=True, timeout=30)
    summary = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else out.stderr.strip()
    print(f"mgmt={values['netbird.client.management']} signal={values['netbird.client.signal']} "
          f"relays={values['netbird.client.relays.available']}/{values['netbird.client.relays.total']} "
          f"peers={values['netbird.client.peers.connected']}/{values['netbird.client.peers.total']} | {summary}")
    if "failed: 0" not in out.stdout:
        return 2
    return 0 if st.get("daemonStatus") != "Unavailable" else 1


if __name__ == "__main__":
    sys.exit(main())

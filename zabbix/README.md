# Zabbix (Mac Studio)

Zabbix **7.4** server runs on the Mac Studio in jax's Docker Desktop. The web UI and API are at
**https://192.168.4.248:8500** (LAN; nginx in front, self-signed cert; the netbird IP doesn't answer on 8500).
The Mac's own agent is `zabbix_agentd` (Homebrew, user jax) reporting to `127.0.0.1:10051`.
Alerts: action "Report problems to Zabbix administrators" → Gmail media (users jax, mdella).

| Folder | What |
|---|---|
| [`netbird/`](netbird/) | NetBird server monitoring (droplet `netbird.cstone.com`): agent, templates, NetBird health checks, client-side check from the Mac, dashboard |

## API access for the scripts
The scripts read an API token from `~/.config/zabbix/api-token` (mode 600) and never print it. Create one in the
UI (User settings → API tokens) and save it without it passing through a terminal history or chat:
```bash
mkdir -p ~/.config/zabbix && read -rs T && printf '%s' "$T" > ~/.config/zabbix/api-token && chmod 600 ~/.config/zabbix/api-token; unset T
```

---

# NetBird monitoring (`netbird/`)

Host **`netbird.cstone.com`** (visible name "NetBird (mdella)", hostid 10788). Tag on everything NetBird-specific:
`component: netbird`. Dashboard: **Dashboards → "NetBird health"**.

## What is checked
**Outside-in (pre-existing, unchanged):** public ports 80/443/22 (+ mail ports, which report "not responding"
because there is no mail server), DNS A/AAAA, STUN 3478/udp, login-page content. The 7 port checks are bound
to the public-IP interface (82), so they keep testing public exposure.

**Agent (added 2026-09-25):** Zabbix Agent 2 7.4.15 on the droplet, reached over **netbird** at
`100.101.19.127:10050` (peer `cis92.cstone.to`) as the host's main agent interface. Templates
*Linux by Zabbix agent* and *Docker by Zabbix agent 2* (the agent can read the Docker socket).
2 Docker items are "not supported" (`docker.kernel_mem*.enabled`: fields removed from newer Docker APIs), which is harmless.

**Server-side NetBird health:** the combined `netbird-server` container (management + signal + relay + STUN)
exposes Prometheus metrics on its docker-internal IP `:9090/metrics` (not published). The droplet's agent reads it
every minute (`web.page.get[{$NETBIRD.METRICS.IP},/metrics,{$NETBIRD.METRICS.PORT}]`, history 0), and dependent
items extract:

| Item | Normal |
|---|---|
| `netbird.signal.peers`, `netbird.relay.peers`, `netbird.mgmt.streams` | ≈ number of connected peers (8 on 2026-09-25) |
| `netbird.mgmt.http5xx.rate` | 0 |
| `netbird.mgmt.sync.rate`, `netbird.relay.reconnect.rate` | low activity |
| `netbird.server.ip` | equals `{$NETBIRD.METRICS.IP}` |

**Client-side (the Mac's view):** `netbird_zabbix_status.py` runs every 60 s (LaunchDaemon
`com.mdella.netbird-zabbix`, as mdella) and pushes `netbird status --json` as trapper items `netbird.client.*`:
management/signal connected, relays available/total, peers connected/total/P2P/relayed, names of peers not
connected, error text, daemon version.

## Alerts (all tagged `component: netbird`)
| Severity | Trigger |
|---|---|
| High | metrics endpoint unreachable 5 min (server down/hung) |
| High | 0 peers connected to signal for 10 min |
| High | container netbird-server / -traefik / -dashboard / -proxy not running, or no state for 15 min |
| High | Mac client: cannot reach management / signal disconnected (3 checks) |
| Warning | fewer than `{$NETBIRD.PEERS.MIN}` (3) peers; management API 5xx for 10 min; Mac client relay/STUN unavailable 10 min |
| Average | server container IP changed (macro stale); Mac client check not reporting 10 min |

The Docker template alone would miss a clean stop or a removed container (its triggers need an error exit or a
failing health check, and none of the NetBird containers define one). Client-side triggers depend on the
server-side "metrics endpoint unreachable", so a server outage raises one alert, not several.

## Known caveat: the metrics IP
`{$NETBIRD.METRICS.IP}` (172.30.0.3) is the container's docker-network IP and can change when `netbird-server` is
recreated. The "server container IP changed" trigger reports it; fix by updating the macro to the value of
"NetBird: server container IP". Permanent fix on the droplet: a static `ipv4_address` for `netbird-server` in its
compose file, or publish `127.0.0.1:9090:9090` and set the macro to `127.0.0.1`.

## Files
| File | Purpose |
|---|---|
| `netbird/netbird_zabbix_status.py` | client-side check (stdlib only; run with `uv run --no-project --python 3.12`) |
| `netbird/com.mdella.netbird-zabbix.plist` | LaunchDaemon; runs the script **from this repo clone** (`~/projects/turing-pi-k3`), so keep that clone on `main` |
| `netbird/provision/zbx.py` | minimal API client (token from `~/.config/zabbix/api-token`) |
| `netbird/provision/10…60_*.py` | recreate the whole setup in order: host/templates → server items → server triggers → client items → client triggers → dashboard. Idempotent |

Install / reinstall the client check on the Mac:
```bash
sudo install -o root -g wheel -m 644 zabbix/netbird/com.mdella.netbird-zabbix.plist /Library/LaunchDaemons/
sudo launchctl bootout system/com.mdella.netbird-zabbix 2>/dev/null
sudo launchctl bootstrap system /Library/LaunchDaemons/com.mdella.netbird-zabbix.plist
tail -f ~/Library/Logs/netbird-zabbix.log        # one line per minute: mgmt=1 signal=1 relays=2/2 peers=7/10 | sent: 12 …
```
Plist changes need `bootout` + `bootstrap`; `launchctl kickstart -k` keeps the old definition.

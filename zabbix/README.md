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
`component: netbird`. Dashboard: **Dashboards → "NetBird health"**. Tiles labelled "Mac Studio client" show the NetBird client on the Mac Studio (the client-side check below). The server version is not shown (its metrics expose none). Images on the droplet (`/root/docker-compose.yml`) are **pinned since 2026-09-26**: `netbirdio/netbird-server:0.79.0`, `netbirdio/reverse-proxy:0.79.0`, `netbirdio/dashboard@sha256:b96c67fe89aaed7164513579d00565bd4326d8a5b8b8ee8c8ccf9ca7efa3f288` (the build that was running; it matched no version tag), `traefik:v3.6`. Upgrade deliberately: change the tag, `docker compose pull && docker compose up -d`. Changing an image reference recreates the containers (a brief NetBird outage) even when the image is identical.

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
| `netbird.mgmt.sync.rate`, `netbird.relay.reconnect.rate` | low activity (0 right after a server restart: the counters are absent until first used) |
| `netbird.server.ip` | equals `{$NETBIRD.METRICS.IP}` |

**Client-side (the Mac's view):** `netbird_zabbix_status.py` runs every 60 s (LaunchDaemon
`com.mdella.netbird-zabbix`, as mdella) and pushes `netbird status --json` as trapper items `netbird.client.*`:
management/signal connected, relays available/total, peers connected/total/P2P/relayed, names of connected peers
with connection type (`netbird.client.peers.up`, plain text; `netbird.client.peers.html`, the same as an HTML bulleted list in 3 columns with P2P in green, shown on the dashboard by an Item history widget with display = HTML) and of peers not connected
(`netbird.client.peers.down`, kept for troubleshooting, not on the dashboard), error text, daemon version.

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

## Other NetBird checks on this Zabbix (not from this folder)
The Mac Studio's own host (`Richards-Mac-Studio`, jax's `zabbix_agentd`, LaunchAgent `gui/502/com.zabbix.agentd`) has
UserParameters in `/opt/homebrew/etc/zabbix/zabbix_agentd.conf.d/`:
- `mac.netbird.peer_status[<peer fqdn>]` (`netbird.conf` → `scripts/netbird_peer_status.sh`), used by the trigger
  "Netbird: k3-node1 not connected (Ollama unreachable from k3s cluster)";
- (`mac.netbird.peers.connected.list` from `netbird_peers_list.conf`, added by Admin 2026-09-26, was **removed** the same day:
  it duplicated `netbird.client.peers.up`. Config kept as `/opt/homebrew/etc/zabbix/netbird_peers_list.conf.removed-20260926`.)

The peer_status check calls **`/usr/local/bin/netbird`** (the NetBird.app client). They originally called `/opt/homebrew/bin/netbird`,
which disappeared when the unused Homebrew `netbird` formula was uninstalled (2026-09-26): peer_status returned
`not_found` and the list went empty until the paths were changed (backups `*.bak-20260926`) and the agent restarted
(`sudo launchctl kickstart -k gui/502/com.zabbix.agentd`; `-R userparameter_reload` isn't supported on macOS).

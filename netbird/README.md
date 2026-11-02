# NetBird (self-hosted, https://netbird.cstone.com) — remote access to the home cluster

Management 0.82.0 and dashboard 2.96.0 since 2026-11-02 (clients vary; nodes 0.82.0), peer DNS domain `cstone.to` (e.g. `k3-node1.cstone.to`). API automation: service
user **`homelab-automation`** (Admin), token on node1 in `~/.netbird-api` (`NB_API_TOKEN`, `NB_API_URL`), never in git.


**Upgrading the control plane:** it's Docker Compose on the droplet, in `/root/docker-compose.yml`, with SQLite as the store. Pull the
new images first, stop `netbird-server`, copy the `root_netbird_data` volume plus the compose and config files to a dated folder in
`/root/backup`, then pin the new versions and run `docker compose up -d --no-deps netbird-server dashboard proxy`. Rolling back means
restoring that copy too, since the upgrade migrates the database. `netbird-server` has a static IP (`172.30.0.3`) so Zabbix's
`{$NETBIRD.METRICS.IP}` stays valid.

## How the house is reached from the road

NetBird **Network "SV Kube Network"**: resource `192.168.4.0/22` (in group `kube-lan`), routing peers
**k3-node4** (original) and **k3-node3** (added 2026-10-08 for HA), masquerade on. Policy **"Kube Network Access"**:
group **Users** → `kube-lan`. So a device in *Users* reaches every cluster IP (`.100` API VIP, `.201` ingress,
`.208` S3, …) at the **same address at home (LAN) and away (tunnel)** — no load balancer or split IPs needed.
Network **"Scotts Valley EERO Network"** (router k3-node4) publishes single hosts `.100`, `.201`, `.209`.

Group *Users* = the owner's MacBook + iPad (2026-10-08). Add a device by putting its peer in *Users*.

Gotcha: NetBird drops traffic that kube-proxy forwards from the netbird interface (see `../honcho/`). Routed traffic is
fine as long as the routing peer isn't the node announcing the MetalLB VIP (2026-10-08: `.201` and `.208` are announced
by k3-node2, routers are node3/node4). If a VIP fails over onto a router node and remote access to it breaks, that's why.

**Update 2026-11-02:** a test from a remote peer failed even though node2 announces `.201` and the router was node4. SYNs reach
node4's `wt0`, kube-proxy's `KUBE-EXT` rule for `.201:443` counts them, and then they vanish: no conntrack entry, nothing reaches
the ingress pod, and NetBird's own forward rule stays at 0 packets. So the note above no longer holds, and `.201` should be
treated as unreachable through a routing peer that runs kube-proxy. Moving the router off the cluster fixes it: see below.

**OPNsense as router (2026-11-02):** the firewall is peer `geekstyle-fw1` and routes network `Della Home Cluster`, which so far holds
`ingress-nginx` (`192.168.4.201/32`, TCP 80 and 443) and `gitlab-ssh` (`192.168.4.211/32`, TCP 22), both open to all peers. Confirmed from a remote peer: the websites load through it, other ports on `.201` don't connect, and
the peer's own LAN using the same `/22` doesn't get in the way. Plugin settings matter here: `acceptServerRoutes` must be **on**, because off
means `--disable-server-routes`, "won't act as a router". `acceptClientRoutes` and DNS stay off, so the firewall doesn't take routes or DNS
from NetBird. `wt0` isn't assigned as an interface and it works anyway. The rest of `PLAN-opnsense-router.md` is still to do: the other
resources, removing node3 and node4 as routers, and tightening policies.

DNS: nameserver group `geekstyle public` sends `geekstyle.net` to 1.1.1.1 and 8.8.8.8 for every peer outside the cluster, so a local
resolver that strips private answers can't hide LAN-only names. Policy `All peers to ingress` lets all peers reach `192.168.4.201/32`
on TCP 80 and 443, through OPNsense. A /32 also wins over a remote site's own `192.168.4.0/22`: confirmed in the route table of a peer on such a LAN.

Hardware note: k3-node1…4 are RK3588 16 GB boards with 1 TB NVMe each in the Turing Pi chassis. The `rpi-101…104`
peers are Raspberry Pis in Santa Rosa (previously Soledad), currently powered off; `rpi-sr-101` is the one running Pi there.

## Planned (S3 over LAN + netbird)
`s3.geekstyle.net` → ingress-nginx `192.168.4.201` with a Let's Encrypt cert (cert-manager DNS-01): OPNsense Unbound
host override for home devices + a NetBird nameserver group (match domain `s3.geekstyle.net` → OPNsense
`192.168.4.1`, for group *Users*) for remote ones. No public DNS record, no Cloudflare tunnel.

## Home LAN quirk: two IPv4 subnets on one wire (fixed 2026-10-08)

OPNsense's LAN port (`igb0`) carries **`192.168.1.0/24`** (client devices: laptops, phones, the Turing Pi BMC;
gateway `192.168.1.1` CARP VIP) **and `192.168.4.0/22`** (cluster; gateway `192.168.4.1` IP alias), plus one IPv6 /64
for everything. A laptop at `192.168.1.x` reaching a cluster IP is routed by OPNsense *in and out of the same port*.

Symptom: from the owner's Mac (`192.168.1.55`) `curl http://192.168.4.208:8333/` connected but then hung ("Read timeout",
"0 bytes received") while IPv6 to the nodes worked. A capture on k3-node2 showed the SYN arriving (via OPNsense) and
the SYN-ACK leaving, but the Mac's ACK + request never arriving — the Mac had been sent an **ICMP redirect** by OPNsense
("go direct to 192.168.4.208"), which it can't actually reach directly from another subnet.

Fix: OPNsense tunables `net.inet.ip.redirect = 0` and `net.inet6.ip6.redirect = 0` (both are the OPNsense defaults;
they had been set to 1). System → Settings → Tunables. Likely also the cause of "BMC unreachable from the nodes via
OPNsense (asymmetric path)" during the node2 rebuild. A cached redirect on a client clears by itself after a few
minutes (macOS: `sudo route delete 192.168.4.208` to clear immediately).

### Still broken after the redirect fix → HAProxy relay on OPNsense (2026-10-08)

Turning redirects off didn't help. Reproduced with a simulated client on node1 (`ip netns macsim`, macvlan on eth0,
`192.168.1.250/24`, gateway `192.168.1.1`): every IPv4 TCP connection from the house subnet into `192.168.4.x` connects
and then stalls. OPNsense's own capture shows it forwards the client's empty ACKs out the same port **twice** and they
never reach the node; SYN/FIN/data get through. Ruled out: redirects, pf state mismatches, offloading (all off), shaper,
pf priority tags, CARP gateway.

**Physical cause found:** node↔node latency ~0.5 ms, but node↔OPNsense ~5–6 ms with jitter on both LAN addresses — the
Turing Pi and OPNsense are not on the same wired switch; there's a wireless (eero bridge/mesh) hop between them. That hop
is what mangles the hairpinned traffic, and it also caps anything crossing it (S3 through the relay ~5 MB/s with
hundreds of TCP retransmits, vs 39–71 MB/s node-local). It also carries all cluster↔internet traffic (Cloudflare tunnel).
**Real fix: wire OPNsense's LAN, the Turing Pi uplink and the eero onto the Arista switch** (flat first, VLANs later).

Workaround until then — **HAProxy on OPNsense (TCP mode)** terminates house-side connections on OPNsense itself and
opens new ones to the cluster, so nothing is hairpin-forwarded:

| House address (OPNsense IP alias, outside DHCP range .41–.245) | → cluster |
|---|---|
| `192.168.1.20:80` / `:443` (frontends `relay-ingress-http/https`) | ingress-nginx `192.168.4.201:80/443` |
| `192.168.1.21:8333` (frontend `relay-s3`) | SeaweedFS S3 `192.168.4.208:8333` |

Backends/servers `cluster-*`, no health checks, client/server timeouts 3600 s. Verified from the simulated house client:
S3 403 instantly, ingress 404 (no Host), authenticated 50 MB S3 round trip byte-identical (~5 MB/s — the wireless hop).
First attempt used `.201`/`.208`, which are inside the DHCP range — `.208` was already a house device (IP conflict) — so
relay addresses must stay outside `.41–.245`.

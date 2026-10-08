# NetBird (self-hosted, https://netbird.cstone.com) — remote access to the home cluster

Clients v0.79.0, dashboard v2.93.0, peer DNS domain `cstone.to` (e.g. `k3-node1.cstone.to`). API automation: service
user **`homelab-automation`** (Admin), token on node1 in `~/.netbird-api` (`NB_API_TOKEN`, `NB_API_URL`), never in git.

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

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

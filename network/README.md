
## Core switch and node DNS (2026-10-31)

`geekstyle-sw1` (Arista 7050TX-64, EOS 4.28) was the cluster's gateway until 2026-11-01 (now OPNsense, see below): `192.168.4.1` is its Vlan14 address, in VRF BLUE
(`show ip route vrf BLUE`). Vlan10 is `192.168.1.5/24`; the default route points at the OPNsense CARP address
`192.168.1.1`, and OPNsense routes `192.168.4.0/22` back through `192.168.1.5`. Turing Pi g0 is on VLAN 10 (BMC), g1 is a
VLAN 14 trunk (nodes). IPv4 is routed by the switch; IPv6 is routed by OPNsense (see below).

The switch is not a DNS server, so nodes must not use `192.168.4.1` for DNS. All four nodes now use `1.1.1.1` in netplan
(nodes 2-4 had `192.168.4.1`, which stopped answering when the address moved from OPNsense to the switch). Public DNS
also answers the LAN-only names (`registry`, `s3`).

Changed with `netplan generate` plus `resolvectl dns eth0 ...`, not `netplan apply`, to avoid touching `eth0` on a live
node. The previous file on each node is `/root/netplan-before-dns-20261031.yaml`.

All four nodes now have the same `/etc/netplan/01-network.yaml`, apart from their addresses, MAC and node1's extra Ziti
address. Node2 was moved over from `50-cloud-init.yaml` on 2026-11-01 (kept as `.orig`), with cloud-init's network
config disabled in `/etc/cloud/cloud.cfg.d/99-disable-network-config.cfg`. The generated networkd config for `eth0` was
identical before and after. Node OS config is now managed by Ansible, kept on scm.geekstyle.net rather than here.

## IPv6 on VLAN 14, from OPNsense (2026-11-01)

EOS 4.28 has no DHCPv6 or prefix-delegation client, and Starlink's /56 changes (it has already changed once since the cluster was
built), so OPNsense routes IPv6 for VLAN 14 directly and nothing pins the prefix:

- sw1 `Ethernet5` (to OPNsense igb0) is a trunk: native VLAN 10, allowed 10,14.
- OPNsense interface `BLUE_V14` (`vlan01` = igb0 tag 14) has no IPv4. IPv6 is Identity Association on WAN, prefix ID
  `0x40`, reserved range 16, so VLAN 14 is `<prefix>:40::/64` (gateway `::1`).
  `<prefix>` in this file = the first 56 bits of the current Starlink /56; LAN is `<prefix>:00::/64`.
  LAN keeps prefix ID `0x0` with range 64 (`00`–`3f`, the eero's /60s); the next free block for a new VLAN is `0x50`.
- Router advertisements (radvd) on BLUE_V14 are *assisted*: SLAAC plus the M/O flags, so networkd also runs DHCPv6.
- Kea DHCPv6 serves a dynamic-prefix subnet on BLUE_V14: addresses `<prefix>:40::1000+` and one delegated /64 per node from
  `<prefix>:48::/64`–`<prefix>:4f::/64`. Kea installs each delegated prefix's route via the node's link-local address.
- For that route, Kea needs the node's MAC, so every node has
  `/etc/systemd/networkd.conf.d/50-duid-link-layer.conf` with `[DHCPv6] DUIDType=link-layer` (DUID-LL instead of
  the systemd DUID-EN). Applied with `systemctl restart systemd-networkd`, one node at a time (worker first), which left
  IPv4 and the nodes' Ready state unaffected.
- OPNsense's host discovery service had to be restarted to see the new interface before Kea's route installer could
  resolve next hops; check that first if a delegated prefix has no route (`netstat -rn -f inet6` on the firewall).

Still open:

- ~~node1's static `<prefix>:00::f:101` (the Ziti edge router)~~ Removed 2026-11-09, see "Git over SSH and Ziti" below.
- ~~The nodes' IPv6 InternalIP is still the old LAN SLAAC address~~ Fixed 2026-11-08, see "Internal IPv6 on ULAs" below.

## Inbound IPv6 aliases moved to VLAN 14 (2026-11-06)

The public IPv6 rules (WAN seq 200 SSH and seq 300 ping, destination `k3s_cluster` → `k3s_nodes_v6`) still used a
Dynamic IPv6 Host alias bound to **LAN**, so they resolved to the nodes' old `<prefix>:00:<host id>` SLAAC addresses
after the nodes moved to VLAN 14. Alias `k3s_nodes_v6` is now bound to `opt1` (BLUE_V14) and resolves to
`<prefix>:40:<host id>` for all four nodes; it still follows the prefix. Config backup before the change on node1 in
`~/opnsense-backups/` (not in git).

Still pending:
- LAN rule seq 41 (an allow rule for a /60 of the *previous* Starlink prefix) is dead and should be deleted.
- `git_ssh_v6` (rule 210) and the MetalLB/DNS address `<prefix>:00::cafe:200` are still on the LAN /64, so git over SSH
  via public IPv6 doesn't reach GitLab. Moving it needs a decision on the prefix-proof design.

## Internal IPv6 on ULAs, `fd00:<vlan>::/64` (2026-11-08)

Goal: nothing inside the cluster depends on the Starlink prefix. Only internet traffic (outbound, and the inbound
services) uses public addresses. ULA plan: one `/64` per VLAN with the VLAN number in the second group, so VLAN 14 is
`fd00:14::/64` (nodes `fd00:14::101`-`104`, MetalLB `fd00:14::200`-`220`, OPNsense `fd00:14::1`), LAN would be
`fd00:10::/64`. Pods (`fd10:42::/56`) and services (`fd10:43::/112`) were already on ULAs; changing those would mean a
cluster rebuild. `fd00::` isn't a random RFC 4193 global ID; accepted, nothing we connect to clashes with it.

Found before the change:
- No node had `node-ip` set, so k3s registered a public SLAAC address as each node's IPv6 InternalIP.
- Node1's flannel VXLAN endpoint was its static public `<prefix>:00::f:101`. Once the nodes moved to VLAN 14 the
  others had no on-link route to that `/64`, so **pods on node1 had no IPv6 to pods on any other node** (IPv4 fine).

Done:
1. `fd00:14::10N/64` added to every node's netplan via Ansible (`netplan_extra_addresses` in the private inventory,
   `netplan generate` only) and live with `ip addr add`. The old `fd00::/64` stays until the MetalLB move is done.
2. `/etc/rancher/k3s/config.yaml` on each node: `node-ip: "192.168.4.10N,fd00:14::10N"`, and on the servers
   `fd00:14::101`-`103` added to `tls-san` (backups `config.yaml.bak-20261107-ula` on node4, `.bak-20261108-ula` on
   nodes 1-3). Etcd snapshot `pre-ula-20261108` taken first. Restarted one node at a time: node4, 3, 2, 1. IPv4 stays the
   first `node-ip` address, so etcd (peer URLs on IPv4) was unaffected.
3. **Gotcha:** flannel on the other nodes doesn't pick up a changed `public-ipv6` annotation; it reads the
   peers' VXLAN endpoints only when its own k3s starts (`bridge fdb show dev flannel-v6.1`). So the first round left stale
   entries, and nodes 4, 3, 2 needed a second restart. After that every node's FDB lists only `fd00:14::`, and pod IPv6
   works between all node pairs.
4. The VIP was on node2, so the API through `192.168.4.100` was unavailable for about a minute during its restarts.

MetalLB (same day): range `fd00:14::200-fd00:14::220` added to `default-pool`, then each IPv6 service pinned with
`metallb.io/loadBalancerIPs` (its unchanged IPv4 + new IPv6), then the old `fd00::200-fd00::220` range removed. Manifest:
[`metallb-default-pool.yaml`](metallb-default-pool.yaml). Backups of the pools and services on node1 `~/metallb-backups/`.

| Service | IPv4 | IPv6 |
|---|---|---|
| ingress-nginx-controller | 192.168.4.201 | fd00:14::200 |
| portainer | 192.168.4.200 | fd00:14::201 |
| monitoring-grafana | 192.168.4.202 | fd00:14::202 |
| monitoring-kube-prometheus-prometheus | 192.168.4.210 | fd00:14::210 |

Prometheus's pin is in `prometheus/prometheus-lb-values.yaml`. The other three were annotated with `kubectl annotate`:
Helm 3 keeps fields it never set, so upgrades keep them, but a reinstall drops them (MetalLB would then auto-assign from
the pool). Checked from node2: ingress (scm Host header), Grafana, Prometheus and Portainer answer on IPv4 and on the new
IPv6 addresses. The addresses don't answer ping (kube-proxy doesn't reply to ICMP on LB addresses); use HTTP.

`fd00::/64` removed the same day: `netplan_ula` is `fd00:14::10N` in the inventory (netplan regenerated, `fd00::10N`
deleted live with `ip addr del`) and `fd00::101`-`103` dropped from `tls-san`. That config change takes effect at each
server's next k3s restart; the serving certificate keeps the old names until it's regenerated, which is harmless.
Pod IPv6 between all node pairs and the `fd00:14::` service addresses checked again afterwards.

Cloudflare-published sites (scm, blog, pages, ...) don't depend on our prefix in either direction: their public AAAA
records are Cloudflare's anycast addresses, cloudflared connects *out* to Cloudflare (over IPv4, `198.41.x`), and its
origin is the in-cluster `ingress-nginx-controller` Service name. A prefix change needs nothing there.

### Phase 2: OPNsense and DNS (2026-11-09)

- OPNsense Virtual IP (IP alias, single firewall so no CARP) `fd00:14::1/64` on `opt1`/BLUE_V14. The interface's own
  IPv6 stays the tracked Starlink `/64`; radvd does not advertise the alias prefix (nodes got no extra address).
  Config backup before the change on node1 in `~/opnsense-backups/` (not in git).
- No new firewall rules: LAN rule 21 already passes LAN IPv6 to any destination, and BLUE_V14 rule 420 passes VLAN 14
  IPv6 out; replies are stateful. The firewall resolves the MetalLB addresses on `vlan01` by NDP (checked for `::200`
  and `::202`).
- Unbound host overrides, AAAA `fd00:14::200` (ingress-nginx) for `s3`, `registry`, `uptime`, `www-dev` and `argocd`.
  `argocd` also got an A override (`192.168.4.201`): once a name has any host override, Unbound answers only from the
  overrides, so an AAAA alone would have hidden its public A record. The other four already had A overrides.
- Pods resolve `geekstyle.net` through Unbound (CoreDNS forward), so they now get the AAAA too; checked from a test pod:
  `uptime` 302 and `registry` 401 (no credentials), both via `fd00:14::200`. None of these ingresses has a source
  allowlist, so IPv6 clients are treated the same as IPv4 ones.
- Clients prefer IPv4 over a ULA when a name has both (RFC 6724 default policy), so the AAAA records are mostly a
  fallback. NetBird routes only `192.168.4.0/22`, so NetBird clients keep using IPv4.

### Git over SSH and Ziti (2026-11-09)

- **Git over SSH:** MetalLB `gitlab-ssh` IPv6 moved from the public `<prefix>:00::cafe:200` (LAN /64, unreachable since
  the nodes moved to VLAN 14) to `fd00:14::cafe:200`. OPNsense port-forwards WAN IPv6 TCP 22 for alias `git_ssh_v6`
  (Dynamic IPv6 Host, now on BLUE_V14, so `<prefix>:40::cafe:200`) to it; rule 210 passes the new host alias
  `git_ssh_ula`. Unbound `git` AAAA → the ULA, Cloudflare AAAA → `<prefix>:40::cafe:200` (both 2026-11-09). Tested from outside (Ziti controller): SSH banner on the public address.
  Only the public Cloudflare AAAA follows the prefix. Details in `gitlab/README.md` "Git over SSH".
- **Ziti:** node1's router doesn't need an inbound address: all its connections are outbound (controller and fabric
  links over the node's DHCPv6 address, which follows the prefix; node2 over IPv4). The static `::f:101` was unused, so
  it's gone from netplan (inventory MR) and from the interface. The routers' advertised names `k3-node1/2.cstone.com`
  (FreeDNS, not Cloudflare) still have AAAA records on a long-dead prefix; edge clients fall back to the A records
  (`192.168.4.10N`, LAN/NetBird). If they're ever needed from the internet, use the same port-forward pattern as git. The hermes-browser policy already blocks `fc00::/7`, which covers all of these.

## IPv4 routing moved to OPNsense (2026-11-01)

`192.168.4.1` is now a CARP address (vhid 14) on OPNsense `BLUE_V14`, with OPNsense itself at `192.168.4.2/22`; the nodes'
gateway did not change, so nothing on the nodes was touched. sw1 `Vlan14` has no IP (L2 only, the DHCP helper is gone);
sw1 still routes only its own Vlan10 address. Removed on OPNsense: the `192.168.4.0/22 via geekstyle-sw1` static route,
the manual source-NAT rule (automatic NAT now covers BLUE_V14), the LAN rule for `192.168.4.0/22`, and DHCP option 121.
IPv4 between VLAN 10 and VLAN 14 now goes through the firewall and its rules. Unbound listens on BLUE_V14 too
(`192.168.4.1`, `<prefix>:40::1`); Kea DHCPv6 hands the nodes `<prefix>:40::1` as a DNS server.

Gotcha: deleting the static route also deleted the kernel's *connected* `192.168.4.0/22` route on vlan01 (VLAN 14 IPv4
was down ~2 min, 2026-11-01 00:51-00:53Z); `/api/interfaces/overview/reloadInterface/opt1` restored it.

Cluster state seen during this (not caused by it): all four nodes cordoned since 2026-10-30 19:37Z (the cluster move),
56 pods not Running, including ingress-nginx, coredns, cert-manager, cloudflared and the Longhorn CSI controllers, so
MetalLB announces nothing for `192.168.4.201` until the nodes are uncordoned.

## PLANET switch on sw1 Ethernet13 (2026-11-01)

The small switch in front of the SolarEdge inverter (see [`solaredge/`](../solaredge/README.md)) is a **PLANET
IGS-5225-4UP1T2S** industrial PoE managed switch (firmware 4.440190920, 2019). Its uplink Gi1/3 goes to sw1 Et13
(access VLAN 10), so its untagged management VLAN 1 is on the LAN.

- Management: **static `192.168.1.6/24`**, gateway and DNS `192.168.1.1`, hostname `planet-sw`; DNS name
  `planet-sw.geekstyle.net` is an Unbound host override (outside Kea's `.41`-`.245` pool). NTP enabled (pool.ntp.org).
- It shipped on factory settings (`192.168.0.100`, clock at 1970); it was reached over its IPv6 link-local address
  (`fe80::aaf7:e0ff:fe63:95cc`, SSH needs `-o HostKeyAlgorithms=+ssh-rsa`).
- **Why static, not DHCP:** its DHCP client sent 21 DISCOVERs and counted 0 OFFERs received, although Kea answered every
  one (unicast to the offered address, which every other client accepts). Probably the firmware only accepts broadcast
  offers without setting the broadcast flag.

Kea note seen while debugging: Kea opens one raw socket per address on igb0 (`.2`, CARP `.1`, HAProxy `.20`/`.21`), so it
processes every broadcast DISCOVER four times and sends two different offers (startup warning
`DHCPSRV_MULTIPLE_RAW_SOCKETS_PER_IFACE`). Clients cope (they take the first), but it burns through offered addresses.

`tcpdump` on an Arista front-panel port (`bash sudo tcpdump -i et13`) only sees traffic to the switch's own CPU, not
forwarded traffic, so it can't be used to watch a device's DHCP.

## Cluster DNS for geekstyle.net via Unbound (2026-11-01)

CoreDNS forwards the `geekstyle.net` zone to OPNsense Unbound on the BLUE_V14 CARP address `192.168.4.1`
([`coredns-geekstyle-forward.yaml`](coredns-geekstyle-forward.yaml), merged into ConfigMap `kube-system/coredns-custom`
as key `geekstyle.net.server`; CoreDNS reloads it without a restart). Everything else still goes to the nodes'
resolvers. Pods now get the same answers as the house: Kea-registered hosts and host overrides such as
`nas`/`garage` → `192.168.4.20`, `solaredge`, `planet-sw`.

Before the switch, every `geekstyle.net` name in this repo was resolved via public DNS and via Unbound. The only real
difference was `s3.geekstyle.net` (public `192.168.4.201`, Unbound `192.168.1.20` = the HAProxy relay, until it moved to `192.168.4.201` on 2026-11-02); no workload
references it, and HTTPS through the relay works from a pod (403 anonymous, valid TLS). The Cloudflare-proxied names
differ only by round-robin. Unbound must stay reachable from the nodes: if the firewall is down, pods can't resolve
`geekstyle.net` names, including public ones such as `scm.` and `auth.`.

Unbound host override `garage.geekstyle.net` → `192.168.4.20` (Garage S3, port 3900) was added the same day.
Backup of the ConfigMap before the change: k3-node1 `~/gitlab-backups/coredns-custom-before-20261101.yaml`.


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
identical before and after. Node config is still applied by hand: there is no Ansible or other host config management.

## IPv6 on VLAN 14, from OPNsense (2026-11-01)

EOS 4.28 has no DHCPv6 or prefix-delegation client, and Starlink's /56 changes (it moved from `2605:59c0:2201:4100::/56` to
`2605:59c0:23a6:dc00::/56`), so OPNsense routes IPv6 for VLAN 14 directly and nothing pins the prefix:

- sw1 `Ethernet5` (to OPNsense igb0) is a trunk: native VLAN 10, allowed 10,14.
- OPNsense interface `BLUE_V14` (`vlan01` = igb0 tag 14) has no IPv4. IPv6 is Identity Association on WAN, prefix ID
  `0x40`, reserved range 16, so VLAN 14 is `<starlink /56>:40::/64` (now `2605:59c0:23a6:dc40::/64`, gateway `::1`).
  LAN keeps prefix ID `0x0` with range 64 (`00`–`3f`, the eero's /60s); the next free block for a new VLAN is `0x50`.
- Router advertisements (radvd) on BLUE_V14 are *assisted*: SLAAC plus the M/O flags, so networkd also runs DHCPv6.
- Kea DHCPv6 serves a dynamic-prefix subnet on BLUE_V14: addresses `…dc40::1000+` and one delegated /64 per node from
  `…dc48`–`…dc4f`. Kea installs each delegated prefix's route via the node's link-local address.
- For that route, Kea needs the node's MAC, so every node has
  `/etc/systemd/networkd.conf.d/50-duid-link-layer.conf` with `[DHCPv6] DUIDType=link-layer` (DUID-LL instead of
  the systemd DUID-EN). Applied with `systemctl restart systemd-networkd`, one node at a time (worker first), which left
  IPv4 and the nodes' Ready state unaffected.
- OPNsense's host discovery service had to be restarted to see the new interface before Kea's route installer could
  resolve next hops; check that first if a delegated prefix has no route (`netstat -rn -f inet6` on the firewall).

Still open:

- node1's static `2605:59c0:23a6:dc00::f:101` (the Ziti edge router) sits in the LAN /64, which is no longer on the
  nodes' segment. Other nodes still reach it on the shared L2, so flannel is fine, but the firewall and the internet
  cannot reach it. It needs a new address in the VLAN 14 /64, and the router's advertised address updated.
- The nodes' IPv6 InternalIP (`kubectl get nodes -o wide`) is still the old LAN SLAAC address picked when k3s started;
  those addresses are gone. Flannel uses `fd00::10x`, which is unaffected. Setting `node-ip` in
  `/etc/rancher/k3s/config.yaml` (e.g. `192.168.4.10N,fd00::10N`) would pin it, at the cost of a k3s restart per node.

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

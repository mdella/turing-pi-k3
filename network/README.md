
## Core switch and node DNS (2026-10-31)

`geekstyle-sw1` (Arista 7050TX-64, EOS 4.28) is the cluster's gateway: `192.168.4.1` is its Vlan14 address, in VRF BLUE
(`show ip route vrf BLUE`). Vlan10 is `192.168.1.5/24`; the default route points at the OPNsense CARP address
`192.168.1.1`, and OPNsense routes `192.168.4.0/22` back through `192.168.1.5`. Turing Pi g0 is on VLAN 10 (BMC), g1 is a
VLAN 14 trunk (nodes). Vlan14 has no IPv6 yet, so the nodes have no IPv6 default route.

The switch is not a DNS server, so nodes must not use `192.168.4.1` for DNS. All four nodes now use `1.1.1.1` in netplan
(nodes 2-4 had `192.168.4.1`, which stopped answering when the address moved from OPNsense to the switch). Public DNS
also answers the LAN-only names (`registry`, `s3`).

Changed with `netplan generate` plus `resolvectl dns eth0 ...`, not `netplan apply`, to avoid touching `eth0` on a live
node. The previous file on each node is `/root/netplan-before-dns-20261031.yaml`. Node2's file is
`50-cloud-init.yaml`; check after its next reboot that cloud-init has not rewritten it.

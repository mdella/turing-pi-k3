# Plan: move NetBird routing to OPNsense + least-privilege NetBird access (2026-10-12)

Status: **plan — nothing changed yet.**

## Why

1. **NetBird on the k3s nodes breaks NetworkPolicy.** On a NetBird routing peer with masquerade, NetBird marks
   every new packet *from* the routed range: `iifname != "wt0" ct state new ip saddr 192.168.4.0/22 meta mark set
   0x0001bd22`. Flannel's VXLAN packets between nodes (node IP → node IP, udp/8472) match. The mark survives
   decapsulation onto the inner pod packet. Its `0x10000` bit is kube-router's "allowed by policy" bit, so the pod's
   REJECT rule is skipped.
   - Proven with `nft monitor trace` on 2026-10-12: a node4 pod → hermes-render on node3 arrives already marked and
     is accepted; the same probe to node2, which isn't a router, is dropped.
   - node3 and node4 are the routers, so **pods on node3 and node4 have no NetworkPolicy enforcement** while they
     route.
   - Taking routing off the k3s nodes removes the rule. NetBird stays on the nodes as plain peers, like node2 today.
2. **NetBird access today is mostly "all ports":**

   | Policy | Source → destination | Today |
   |---|---|---|
   | Kube Network Access | Users → `192.168.4.0/22` | **every IP and port on the cluster LAN** |
   | k3-kube-control Access | Users → .100 | all ports |
   | Users to Servers | Users → SV/SR/DO/Soledad/AWS peers | all ports |
   | SR to SV Servers | SR+DO+Soledad+SV+AWS ↔ same (bidirectional) | all ports. A compromised droplet or Pi reaches every k3s node. |
   | AI Users to SM Servers | AI Users (incl. non-owner laptops) → Mac Studio + Richard's MBP | all ports |
   | AI users to SR Servers | AI Users → rpi-sr-101 | all ports |
   | k3s access to AI servers | SV → SM | all ports |
   | Access to AI servers | SR ↔ SM | all ports |
   | Zabbix Monitoring | SM ↔ DO/SR/SV | tcp 10050/10051 ✔ |

   Goal: every policy names specific destinations **and** ports. NetBird's identity-aware policies are the primary
   control; OPNsense filters the NetBird interface as a second layer.

## Fit check (done 2026-10-12, read-only)

| Item | Finding |
|---|---|
| OPNsense | 26.7.6 (FreeBSD 15.1, amd64, 4 GB). **`os-netbird` 1.3_3 is already installed, enabled and running**, but it never enrolled: it's not in the peer list and has no `wt0`. Its routing settings already allow server routes. |
| Placement | OPNsense already has `192.168.4.1/22` on `igb0`. It is the cluster's gateway, so traffic NetBird → cluster is routed in on `wt0` and out on `igb0`: no hairpin, symmetric return path. |
| Masquerade | NetBird docs: *"Masquerade can only be turned off on Linux routing peers."* On OPNsense, cluster services see source `192.168.4.1`. The NetBird identity lives in NetBird and OPNsense logs. |
| Data path | Non-Linux routing peers forward in NetBird's **userspace** router. Throughput is limited by Starlink upload (remote) or the eero hop anyway. |
| Availability | One router instead of two. Acceptable: when OPNsense is down the house has no internet path, so remote access is gone regardless. |
| ⚠ CGNAT range | Starlink WAN gets a CGNAT address in `100.64.0.0/10`; the NetBird network is `100.101.0.0/16`, inside it. Longest-prefix wins, so it should work. Verify right after enrollment that WAN and NetBird both work. |
| ⚠ eero hop | OPNsense ↔ Turing Pi still crosses the wireless hop: ~5 MB/s, and earlier stalls on *hairpinned* TCP. This path isn't hairpinned, but test bulk TCP (S3, git clone). Wiring the Arista switch fixes it properly. |

Alternative if OPNsense can't do it: a small **Linux** box at home (not a k3s node) as the router. That's kernel
mode, and masquerade could be off with a return route on OPNsense. More hardware, same policy work.

## Target access model

**Groups:**
- `Admins`: owner's MacBook, iPad, iPhone. Replaces "Users".
- `AI Users`: drop non-owner devices unless the owner confirms each.
- `Routing Peers`: OPNsense only. No other group, so it receives no routes itself.
- Server groups as today.

**Network "Home cluster"** (router: OPNsense, masquerade on). One `host` resource per service, so a policy can
grant exactly that IP and port:

| Resource | Address | Ports (tcp) | Who |
|---|---|---|---|
| k8s API (kube-vip) | 192.168.4.100 | 6443 | Admins |
| ingress-nginx (GitLab, Hermes, blog, Luna, Cheshire, S3 host, …) | 192.168.4.201 | 80, 443 | Admins |
| Portainer | 192.168.4.200 | 9443 | Admins |
| Grafana | 192.168.4.202 | 80 | Admins |
| openclaw | 192.168.4.203 | 18789 | Admins |
| SeaweedFS S3 | 192.168.4.208 | 8333 | Admins |
| Uptime Kuma | 192.168.4.209 | 80 | Admins |
| Prometheus | 192.168.4.210 | 9090 | Admins |
| ProxySQL | 192.168.4.207 | 3306 | **none by default**; grant ad hoc |
| node SSH | 192.168.4.101–104 | 22 | Admins |
| BMC (optional) | 192.168.1.223 | 443 | Admins |

Not published: .204 (Ghost direct; use ingress), .205 django and .206 echo demo (delete them?), Portainer 9000/8000.

**Peer-to-peer policies:**

| Policy | Rule |
|---|---|
| Admins → SV Servers | tcp 22, 8800, 8801 (Honcho relay) |
| SV Servers → SM Servers | tcp 11434 (Ollama), 8080 (llama-server), ComfyUI port |
| AI Users → SM Servers | tcp 11434, 8080 only. Remove Richard's MBP from SM Servers unless it serves models. |
| AI Users → SR Servers | specific ports after discovery, else remove |
| SR/DO/Soledad/AWS ↔ SV | replace "all, bidirectional" with the flows found in discovery (Ziti controller is the DO droplet; Ziti routers dial out to it, so possibly nothing) |
| Zabbix | keep; split into SM→agents 10050 and agents→SM 10051 (unidirectional) |
| Default | stays disabled |

**OPNsense `NetBird` interface rules** (second layer, mirrors the resource table):
- **Aliases:**
  - `nb_net` = `100.101.0.0/16`
  - `nb_admin_hosts` / `nb_admin_ports` built from the table above
- **Rules:**
  1. pass `nb_net` → `nb_admin_hosts`:`nb_admin_ports`
  2. pass `nb_net` → `This Firewall` udp/tcp 53 (only if a NetBird nameserver group points at OPNsense)
  3. **block + log** everything else, including the OPNsense GUI and SSH over NetBird
- **⚠ To verify in Phase 2:** with the userspace router, pf may see forwarded flows as traffic from the firewall
  itself, not as inbound on `wt0`. If a test block rule doesn't fire, NetBird policies are the only per-port layer
  on this path. Record that in the README.

## Phases

**Phase 0 — prerequisites.**
1. OPNsense config backup to `~/opnsense-backups/` on node1 (not in git).
2. Owner decisions (below).
3. Arista wiring status: not a blocker, but bulk TCP tests depend on it.

**Phase 1 — discover real flows (about a week, read-only).**
- Sample `conntrack` for sources in `100.101.0.0/16` on node1–4 and the routers every minute: destination IP and
  port.
- Do the same on rpi-sr-101 and the Mac Studio if reachable.
- Output: the exact port list for the peer-to-peer policies. Nothing is tightened without evidence of what is used.

**Phase 2 — enroll OPNsense (no user impact).**
1. NetBird dashboard: the owner creates a one-off setup key with auto-group `Routing Peers`. It goes straight into
   the OPNsense UI and never through chat.
2. OPNsense:
   - VPN → NetBird: management URL + key; hostname `opnsense`.
   - Interfaces → Assignments: `wt0` as `NetBird`, enabled, prevent removal.
   - Outbound NAT hybrid with a static-port rule for NetBird UDP, for hole punching behind CGNAT.
3. Check: peer connected (P2P or relayed); WAN still fine; `100.101.x` reachable from OPNsense.
4. Add the interface rules above, plus a temporary block-and-log rule test to settle the pf question.

**Phase 3 — new network, side by side (no user impact).**
1. Create network "Home cluster" with the host resources and router `opnsense`, plus the port-scoped policies for
   `Admins`.
2. The old `192.168.4.0/22` route via node3/node4 stays for now. Clients prefer the more specific `/32` resources, so
   granted services move to OPNsense first.
3. Test from the MacBook, away from home (phone hotspot):
   - every resource and port in the table works;
   - `git clone`, S3 upload and kubectl all work;
   - a non-granted port (e.g. .207:3306) is refused.

**Phase 4 — cut over (minutes; remote access to non-granted IPs ends).**
1. Disable policies "Kube Network Access" and "k3-kube-control Access".
2. Remove node3 and node4 as routers. Delete networks "SV Kube Network" and "Scotts Valley EERO Network".
3. On node3/node4, `nft list table ip netbird` must show **no** `0x1bd22`/`0x1bd21` rules. If they persist, restart
   `netbird` on that node.
4. Re-run the node3 probe: foreign pod → hermes-render must be **refused**, gateway → render **200**. Do the same
   for a protected pod on node4.
5. Remove the temporary signal-cli `NotIn [k3-node3]` affinity from `hermes/k8s/hermes.yaml`.
6. Update docs: `netbird/README.md` (new model; the MetalLB-VIP-on-router gotcha no longer applies),
   `k3s-cluster-notes.md` (close the node3 NetworkPolicy issue), Cilium proposal (the NetBird risk is gone).

**Phase 5 — tighten peer-to-peer policies** with the Phase 1 data. Change one policy at a time, each with a test.

**Rollback.**
- Re-enable the two old policies and re-add node3/node4 as routers. The old networks are kept disabled for 2 weeks
  instead of deleted.
- OPNsense: disable the NetBird service.
- Restore the config backup if needed.

## Decisions for the owner

1. OK to make OPNsense the only NetBird router, with no router failover? (Alternative: a small Linux box.)
2. Who keeps access:
   - non-owner devices in `AI Users`: a guest MacBook, an ASUS Windows laptop, Richard's MBP
   - the server groups' all-port bidirectional access to the k3s nodes
3. Which cluster services to publish (the resource table above). ProxySQL off by default? Delete the demo services
   .205/.206?
4. Run Phase 1 discovery for a week first (recommended), or tighten straight away from the table above.

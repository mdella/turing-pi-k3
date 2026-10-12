# Proposal: replace flannel + kube-router with Cilium (2026-10-11)

Status: **proposal — not approved, nothing installed.**

## Recommendation

Yes, move to Cilium — but **wait for Cilium 1.21.0** (first release tested on Kubernetes 1.37; we run k3s
v1.37.1) and do it as **one planned maintenance window** (~2 h of cluster-wide disruption). Until then, fix the
node3 NetworkPolicy gap directly (diagnosis in progress) and keep signal-cli pinned off node3.

## Why

| Today (k3s defaults, built into the k3s binary) | With Cilium |
|---|---|
| flannel VXLAN pod network | Cilium VXLAN (same CIDRs) |
| kube-router NetworkPolicy as iptables chains — **node3 enforces nothing** (chains present, 0 hits; Docker shares the FORWARD chain there) | policy enforced in eBPF on each pod's interface — independent of iptables ordering, Docker or netbird rules |
| a dropped connection is invisible | **Hubble** shows every flow and every policy drop (CLI + UI) |
| egress rules only by IP range | **FQDN egress rules** (e.g. Hermes may reach only `api.anthropic.com`, `scm.geekstyle.net`, …) |
| kube-proxy iptables, MetalLB L2 | unchanged in phase 1; optional later: kube-proxy replacement, LB IPAM + L2 announcements instead of MetalLB, WireGuard node-to-node encryption |

## Fit check

| Item | Finding |
|---|---|
| Kernel | all 4 nodes `6.1.0-1025-rockchip`: `BPF_SYSCALL`, `BPF_JIT`, `CGROUP_BPF`, `DEBUG_INFO_BTF` (=`/sys/kernel/btf/vmlinux` present), `NET_CLS_BPF`/`NET_ACT_BPF`/`NET_SCH_INGRESS` (modules), `VXLAN`, `WIREGUARD`, `XFRM` ✔ |
| Kubernetes | Cilium **1.20.2** (latest, 2026-09-16) is tested on 1.33–1.36 only. `main` (→ **1.21**) lists 1.34–**1.37**; 1.21.0-pre.3 is out (2026-10-02) |
| Dual-stack | cluster `10.42.0.0/16,fd10:42::/56`, services `10.43.0.0/16,fd10:43::/112`; Cilium cluster-pool IPAM can keep both |
| Memory | nodes 46–62 % used (16 GiB each). Cilium adds roughly agent 200–400 MiB + envoy 50–100 MiB per node, operator ×2, Hubble relay/UI → **~1.5–2.5 GiB cluster-wide** |
| Existing policies | 6 (5 hermes, 1 coder), plain `networking.k8s.io/v1` → enforced as-is. Cilium treats the node itself as the `host` entity: kubelet probes are allowed by default; `ipBlock` with node IPs (none left after the Hermes cutover) would not match host traffic |

## What else touches node networking (risks)

- **k3s embeds flannel; the backend is a cluster-wide server setting** (`flannel-backend` must match on all
  servers), so Cilium's node-by-node "dual overlay" migration doesn't fit k3s well → **big-bang** in one window.
- **Every pod restarts** on the new network: Longhorn volumes re-attach, GitLab's 8–9 GB boot peak, Galera must
  regain quorum, Hermes/Signal down meanwhile. etcd, kube-vip (control-plane VIP via ARP), node-exporter, MetalLB
  speakers and the honcho netbird relay are hostNetwork → unaffected by the CNI swap itself.
- **netbird** (`wt0`, node3/node4 route 192.168.4.0/22 to netbird users) and **Ziti routers** (host tunnel mode,
  iptables TPROXY on node1/node2) rely on the host's iptables/routing → phase 1 keeps kube-proxy and uses
  `bpf.hostLegacyRouting: true` so non-pod traffic keeps the iptables path; no socket-LB.
- **Docker** on node1/node3 keeps its own bridge; unaffected.
- k3s leaves kube-router/flannel iptables chains and the `flannel.1`/`cni0` devices behind → reboot each node
  after switching.

## Plan

**Phase 0 — now.** Finish the node3 diagnosis and fix it with the current stack. signal-cli stays off node3.

**Phase 1 — prep (before 1.21.0 GA).**
1. Test chart + values + our 6 policies in a throwaway k3d cluster on node4 (same kernel) — including a node3-style
   "Docker on the host" case and dual-stack.
2. Write `cilium/values.yaml` (sketch below), pin chart version + image digests.
3. Pre-window: etcd snapshot, Longhorn backups of stateful apps, Galera dump, Hermes delivery ledger empty.

**Phase 2 — window (~2 h).**
1. `helm install cilium` (agents wait for the CNI switch).
2. All servers + node4: `flannel-backend: none`, `disable-network-policy: true` in `/etc/rancher/k3s/config.yaml`;
   restart k3s server by server, then node4.
3. Reboot nodes one at a time (clears flannel/kube-router leftovers; pods come back on Cilium).
4. Verify: `cilium status`, `cilium connectivity test` (namespace-scoped), the node3 probes from this week (render,
   signal-cli, sandboxes refused from foreign pods), Longhorn, GitLab, Galera, Hermes reply + Signal, tunnel sites.

**Phase 3 — optional, later.** Hubble UI behind Cloudflare Access; FQDN egress policies for Hermes, Luna, Coder;
kube-proxy replacement (after checking Ziti/netbird); Cilium LB IPAM + L2 announcements replacing MetalLB;
WireGuard encryption.

**Rollback.** Restore the k3s config (`flannel-backend` back to default, drop `disable-network-policy`),
`helm uninstall cilium`, reboot nodes. Last resort: etcd snapshot restore.

## values.yaml sketch (phase 1)

```yaml
k8sServiceHost: 192.168.4.100      # kube-vip
k8sServicePort: 6443
kubeProxyReplacement: false        # keep kube-proxy (Ziti TPROXY, netbird) in phase 1
routingMode: tunnel
tunnelProtocol: vxlan
ipv4: { enabled: true }
ipv6: { enabled: true }
ipam:
  mode: cluster-pool
  operator:
    clusterPoolIPv4PodCIDRList: ["10.42.0.0/16"]
    clusterPoolIPv4MaskSize: 24
    clusterPoolIPv6PodCIDRList: ["fd10:42::/56"]
    clusterPoolIPv6MaskSize: 64
bpf: { masquerade: false, hostLegacyRouting: true }
enableIPv4Masquerade: true
enableIPv6Masquerade: true
l2announcements: { enabled: false } # MetalLB stays
operator: { replicas: 2 }
hubble: { enabled: true, relay: { enabled: true }, ui: { enabled: true } }
```

## Decisions for the owner

1. Approve the direction (Cilium, big-bang window), or stay on flannel/kube-router once node3 is fixed.
2. Wait for **1.21.0** (recommended) or run 1.20.x on Kubernetes 1.37 (untested upstream).
3. Phase-1 scope: plain swap + Hubble only (recommended), or also kube-proxy replacement / MetalLB replacement.
4. A maintenance window once 1.21.0 is out.

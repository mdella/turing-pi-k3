<div align="center">

# Turing Pi 2.5 — ARM64 Kubernetes Home Lab

### A fully documented HA K3s cluster built on four RK1 compute modules

4× RK1 (RK3588) • 16 GB RAM per node • 1 TB NVMe per node • Ubuntu 24.04

K3s • Embedded etcd • Dual-Stack IPv4/IPv6 • Longhorn • MetalLB • Rancher

</div>

---

## Additional Applications

Beyond the core cluster infrastructure, this repository also documents real workloads deployed on top of the cluster — each with its own installation guide, configuration files, and operational notes. These serve as reference implementations for running production-grade applications on ARM64 Kubernetes in a home lab environment.

| Application | Directory | Description |
|---|---|---|
| [Prometheus](prometheus/README.md) | `prometheus/` | kube-prometheus-stack — Prometheus Operator, Alertmanager, kube-state-metrics, node-exporter; Longhorn-backed TSDB storage |
| [Grafana](grafana/README.md) | `grafana/` | Metrics dashboards via LoadBalancer; ConfigMap-provisioned dashboards for all cluster applications |
| [MariaDB Galera](mariadb/README.md) | `mariadb/` | 3-node synchronous Galera cluster via mariadb-operator; local-path hostPath storage; full test + load-test suite |
| [ProxySQL](proxysql/README.md) | `proxysql/` | Galera-aware MySQL proxy with read/write splitting, connection pooling, and Prometheus exporter |
| [SeaweedFS](seaweedfs/README.md) | `seaweedfs/` | HA distributed object storage with S3-compatible API, MariaDB filer backend, and full load-test results |
| [OpenBao](openbao/README.md) | `openbao/` | Open-source Vault fork; 3-node Raft HA cluster for secrets management and Kubernetes auth |
| [Ghost Blog](ghost/README.md) | `ghost/` | Ghost 5/6 CMS on MariaDB with Longhorn storage, daily S3 backups, security headers, and ingress config |
| [OpenClaw AI Assistant](openclaw-discord.md) | `openclaw-discord.md` | Claude-backed AI agent with Discord front end |
| [Uptime Kuma](uptime-kuma/README.md) | `uptime-kuma/` | Self-hosted uptime monitoring with HTTP/TCP/ping checks and alerting |

---

## Overview

This repository documents the build-out of a production-grade, high-availability Kubernetes cluster on a [Turing Pi 2.5](https://turingpi.com/product/turing-pi-2-5/) board using four RK1 compute modules. The project covers everything from initial OS flashing through cluster deployment, storage, networking, observability, security hardening, and real-world benchmark results — with a growing library of automation scripts and expanded use cases.

The goal is a complete, reproducible reference for anyone running ARM64 Kubernetes on Turing Pi hardware, whether for home lab learning, edge computing, or low-power always-on services.

**Total cluster specs at a glance:**

| | |
|---|---|
| **Nodes** | 4× Turing RK1 (3 server + 1 worker) |
| **CPU** | RK3588: 4× Cortex-A76 + 4× Cortex-A55 per node |
| **RAM** | 64 GB total (16 GB LPDDR4x per node) |
| **Storage** | 4 TB NVMe total (1 TB PCIe 3.0 ×4 per node) |
| **Network** | 1 Gbps per node via Turing Pi 2.5 backplane |
| **Power** | ~30–50 W total cluster draw |
| **OS** | Ubuntu 24.04 Server (ARM64) |

---

## Repository Contents

### 📘 Guides

| Document | Description |
|---|---|
| [turing-pi-k3s-guide.md](turing-pi-k3s-guide.md) | Complete HA K3s cluster deployment — OS setup, networking, K3s, kube-vip, MetalLB, Longhorn, Rancher, monitoring, and maintenance |
| [turing-pi-benchmark-guide.md](turing-pi-benchmark-guide.md) | Step-by-step benchmarking guide — Longhorn storage (kbench/FIO), control plane performance, and CIS security compliance (kube-bench) |
| [benchmark-comparison.md](benchmark-comparison.md) | ARM64 vs. x86 benchmark comparison — storage, control plane, and security results with workload recommendations |
| [openclaw-discord.md](openclaw-discord.md) | Deploying OpenClaw AI assistant on K3s with a Discord front end, Anthropic Claude LLM backend, and optional web search |

### 🔧 Scripts *(coming soon)*

Automation scripts for cluster lifecycle management, benchmarking, backup, and deployment will be organized here as the project grows.

---

## Cluster Architecture

The cluster uses a three-server HA topology with embedded etcd, giving it quorum-based consensus and automatic leader failover without an external database.

```
┌──────────────────────────────────────────────────────┐
│                 Turing Pi 2.5 Board                  │
│                                                      │
│       ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│       │ k3-node1 │  │ k3-node2 │  │ k3-node3 │       │
│       │  Server  │  │  Server  │  │  Server  │       │
│       │  + etcd  │  │  + etcd  │  │  + etcd  │       │
│       └────┬─────┘  └────┬─────┘  └────┬─────┘       │
│            └─────────────┴─────────────┘             │
│                          │                           │
│                  1 Gbps Backplane                    │
│                          │                           │
│                   ┌────────────┐                     │
│                   │  k3-node4  │                     │
│                   │   Worker   │                     │
│                   └────────────┘                     │
│                                                      │
└──────────────────────────────────────────────────────┘
             VIP: 192.168.4.100 (kube-vip)
```

**Software stack:**

| Component | Solution | Purpose |
|---|---|---|
| Kubernetes | K3s (embedded etcd) | Lightweight, ARM64-native HA distribution |
| CNI | Flannel dual-stack | IPv4 + IPv6 pod networking |
| VIP | kube-vip | Floating control plane IP for HA failover |
| Load Balancer | MetalLB (L2 mode) | Dual-stack external service IPs |
| Ingress | Nginx Ingress Controller | HTTP/S routing with dual-stack support |
| Storage | Longhorn | Distributed, replicated NVMe storage |
| Dashboard | Rancher / Portainer | Cluster management UI |
| Monitoring | Prometheus + Grafana | Metrics, dashboards, and alerting |

---

## Benchmark Summary

Full methodology and raw results are in [turing-pi-benchmark-guide.md](turing-pi-benchmark-guide.md). The [benchmark-comparison.md](benchmark-comparison.md) places these results in context against typical x86 K3s deployments.

### Storage (Longhorn via kbench/FIO)

| Metric | Turing Pi (Longhorn) | Turing Pi (Local NVMe) | Typical x86 (Longhorn) |
|---|---|---|---|
| Random Read IOPS | ~8,000–12,000 | ~35,000–50,000 | ~15,000–40,000 |
| Random Write IOPS | ~4,000–6,000 | ~20,000–30,000 | ~8,000–20,000 |
| Sequential Read | ~110 MB/s | ~900 MB/s | ~200–500 MB/s |
| Sequential Write | ~51 MB/s | ~450 MB/s | ~150–400 MB/s |

> **Key finding:** The 1 Gbps backplane limits Longhorn replicated writes to ~51 MB/s. Local NVMe performance is excellent for ARM64. This is a network topology constraint, not an ARM64 limitation.

### Control Plane Performance

| Operation | Turing Pi (ARM64) | Typical x86 |
|---|---|---|
| Cold pod start (25 pods, image pull) | ~45–90s | ~30–60s |
| Cached scale-out (25 pods) | ~3.2s | ~2–4s |
| Scale-in (25→0 pods) | ~8–12s | ~5–10s |
| Pod delete | <1s | <1s |

> **Key finding:** Cached operations are operationally equivalent to x86 for small-to-medium clusters.

### CIS Security Compliance

K3s on Turing Pi achieves the same CIS Kubernetes Benchmark compliance profile as x86 K3s deployments. No ARM64-specific security gaps were identified.

---

## Why Turing Pi?

The Turing Pi 2.5 with RK1 modules offers a unique combination that no x86 platform matches at this price and power point:

- **~$1,000** for a complete 4-node HA cluster with 64 GB RAM and 4 TB NVMe
- **30–50 W** total cluster power draw vs. 300–800 W for equivalent x86
- **Desk-sized** mini-ITX form factor — no rack required
- **Full HA** with automatic etcd failover and control plane VIP
- **Dual-stack IPv4/IPv6** networking throughout
- **Production-grade** storage with Longhorn replication and snapshots

For workloads that don't require x86's peak throughput — home lab learning, edge computing, IoT gateways, always-on services, CI/CD runners, monitoring stacks — this cluster delivers exceptional value.

---

## Getting Started

If you are building this cluster from scratch, follow the guides in order:

1. **[turing-pi-k3s-guide.md](turing-pi-k3s-guide.md)** — Flash Ubuntu, configure networking, deploy the full K3s stack
2. **[turing-pi-benchmark-guide.md](turing-pi-benchmark-guide.md)** — Validate your deployment with storage, control plane, and security benchmarks
3. **[benchmark-comparison.md](benchmark-comparison.md)** — Interpret your results relative to x86 baselines
4. **[OpenClaw guide](openclaw-discord.md)** — Deploy an AI assistant as your first real workload

---

## Roadmap

This repository will grow to include:

- [ ] Automation scripts for cluster bootstrap and node provisioning
- [ ] Helm chart collection for recommended workloads
- [ ] Longhorn backup and snapshot automation
- [ ] GitOps workflows (Flux or ArgoCD)
- [ ] NPU enablement on RK3588 for local AI inference (RKLLM / Qwen)
- [ ] Additional use case guides (media server, home automation, CI/CD runners)
- [ ] Upgrade and maintenance runbooks

---

## Prometheus — Metrics Collection

**Directory:** [`prometheus/`](prometheus/README.md)

The cluster uses **kube-prometheus-stack** (chart v83.6.0, Prometheus Operator v0.90.1) deployed as a single Helm release in the `monitoring` namespace. It bundles Prometheus, Alertmanager, the Prometheus Operator, kube-state-metrics, and node-exporter (one DaemonSet pod per node).

Prometheus TSDB is backed by a **20 Gi Longhorn RWO PVC** for persistence across pod restarts. Prometheus itself is ClusterIP-only — it is accessed through Grafana or via `kubectl port-forward`.

**ServiceMonitor pattern:** Each application in this repo defines its own `ServiceMonitor` with the `release: monitoring` label. The Operator picks these up automatically across all namespaces. No changes to the Prometheus configuration are needed when adding new applications.

**Key installation notes:**
- CRDs must be applied manually with `--server-side` before every install/upgrade — the chart's built-in CRD upgrade Job fails due to RBAC constraints (`crds.enabled: false` in values)
- All three `verticalPodAutoscaler.enabled` flags must be `false` — nil pointer panic if VPA CRDs are not present in the cluster

Full installation steps, upgrade procedure, and ServiceMonitor inventory are in **[prometheus/README.md](prometheus/README.md)**.

---

## Grafana — Metrics Dashboards

**Directory:** [`grafana/`](grafana/README.md)

Grafana is deployed as part of the kube-prometheus-stack release and exposed via MetalLB at **`192.168.4.202:80`** (dual-stack IPv4/IPv6). The Prometheus data source is auto-configured by the chart.

Dashboards are provisioned as **ConfigMaps** in the `monitoring` namespace with the `grafana_dashboard: "1"` label. The Grafana sidecar hot-loads them within ~30 seconds of application — no pod restart required. Each application directory in this repo contains its own dashboard ConfigMap:

| Dashboard | File |
|---|---|
| MariaDB + ProxySQL | `mariadb/grafana-dashboard-mariadb.yaml` |
| SeaweedFS | `seaweedfs/grafana-dashboard-seaweedfs.yaml` |
| OpenBao | `openbao/grafana-dashboard-openbao.yaml` |
| ingress-nginx | `ingress-nginx/grafana-dashboard-ingress-nginx.yaml` |

The stack also ships pre-loaded dashboards for all core Kubernetes components (nodes, workloads, etcd, API server, CoreDNS, scheduler, node-exporter).

> **Note:** Grafana state created through the UI (hand-built dashboards, annotations, user accounts) is stored in an in-pod SQLite database and is not persisted across pod restarts. All dashboards in this repo are ConfigMap-provisioned and survive restarts automatically.

Full access details, provisioning workflow, and operational commands are in **[grafana/README.md](grafana/README.md)**.

---

## MariaDB Galera — Shared Database Cluster

**Directory:** [`mariadb/`](mariadb/README.md)

A 3-node synchronous multi-master MariaDB Galera cluster, deployed via the `mariadb-operator` (the Bitnami chart was ruled out after Bitnami paywalled its images in August 2025). All three server nodes run a replica with writes acknowledged only after they commit on every node — zero data loss on single-node failure.

**Layout:** `mariadb-galera-{0,1,2}` on k3-node3/2/1; 20 Gi `local-path` hostPath PVs per node (Galera handles replication — Longhorn is not used).

**Key bootstrap lessons:**
- CRDs must be installed from a separate `mariadb-operator-crds` chart before the operator
- `local-path` PVCs bind eagerly even with `WaitForFirstConsumer` — PVs must be pre-created with `claimRef` + `nodeAffinity` to prevent wrong-node binding
- Host directories must be pre-created as `999:999` (mysql uid/gid) via `kubectl debug node` before the pods start
- MetalLB LoadBalancer services require `ipFamilyPolicy: SingleStack` for IPv4-only addresses

Full installation steps, schema setup, Galera recovery notes, and load-test results (666 raw rows/s, ~14% ProxySQL overhead, no replication lag) are in **[mariadb/README.md](mariadb/README.md)**.

---

## ProxySQL — Database Proxy

**Directory:** [`proxysql/`](proxysql/README.md)

ProxySQL runs as 2 replicas in front of the MariaDB Galera cluster, providing a single connection endpoint for both in-cluster workloads and external clients. It monitors `wsrep_local_state_comment` every 2 seconds and automatically re-routes writes away from a failed primary.

| Endpoint | Address | Purpose |
|---|---|---|
| In-cluster | `proxysql.mariadb.svc.cluster.local:6033` | Application connections |
| External | `192.168.4.207:3306` | DBA tools / external clients |
| Admin | `proxysql-admin.mariadb.svc.cluster.local:6032` | Internal only |

**Routing:** `SELECT` → reader hostgroup (HG 30); writes and `SELECT ... FOR UPDATE` → writer (HG 10); backup writers promoted automatically to HG 10 on failure.

A `proxysql_exporter` sidecar feeds connection-pool metrics to the MariaDB Grafana dashboard. Full config, routing rules, upgrade procedure, and operational commands are in **[proxysql/README.md](proxysql/README.md)**.

---

## OpenBao — Secrets Management

**Directory:** [`openbao/`](openbao/README.md)

OpenBao is an open-source fork of HashiCorp Vault, deployed as a 3-node Raft HA cluster. It provides secrets storage, dynamic credentials, and Kubernetes pod authentication for workloads in the cluster.

**Important operational note — manual unseal required:** OpenBao uses Shamir secret sharing (5 shares, threshold 3). Auto-unseal is not configured. After any cluster reboot or pod restart, each pod starts sealed and must be unsealed manually:

```bash
kubectl exec -n openbao openbao-0 -- bao status          # check
kubectl exec -it -n openbao openbao-0 -- bao operator unseal  # unseal (repeat for pod-1, pod-2)
```

**Upgrade note:** The StatefulSet uses `OnDelete` update strategy — after `helm upgrade`, pods must be deleted manually. `OrderedReady` means pod-1 and pod-2 won't schedule until pod-0 is unsealed. Unseal pod-0 before proceeding.

Metrics use the `vault_` prefix (Vault-compatible telemetry). Full installation, auth methods, test suite (15 assertions), and common commands are in **[openbao/README.md](openbao/README.md)**.

---

## Ghost Blog

**Directory:** [`ghost/`](ghost/README.md)

Ghost 6.x CMS served at `http://blog.geekstyle.net` via ingress-nginx. Uses a dedicated standalone MariaDB (not the Galera cluster) in the `ghost` namespace, with content on a Longhorn RWO PVC.

| Detail | Value |
|---|---|
| External IP | `192.168.4.204` (MetalLB) |
| Database | Standalone MariaDB 10.11 in `ghost` namespace |
| Content storage | Longhorn 5 Gi RWO PVC |
| Daily backup | `ghost-db-backup` CronJob → SeaweedFS S3 `ghost-backups` bucket, 30-day retention |

**Known issues:**
- `url` env var is set to the LoadBalancer IP (`http://192.168.4.204`) instead of `http://blog.geekstyle.net` — post permalinks, RSS, and email links reference the IP. Fix: `kubectl set env deployment/ghost -n ghost url=http://blog.geekstyle.net`
- TLS not yet enabled — see `CLAUDE.md` Ghost TLS Checklist for the full cert-manager + Let's Encrypt procedure

Full deployment manifests, security headers config, backup CronJob, and test suite (29 assertions, 29/29 passing) are in **[ghost/README.md](ghost/README.md)**.

---

## SeaweedFS — Distributed Object Storage

**Directory:** [`seaweedfs/`](seaweedfs/README.md)

SeaweedFS is deployed in HA mode across all four cluster nodes, providing S3-compatible object storage with a distributed architecture. It was added after the core cluster was running and complements Longhorn (which handles block storage for stateful workloads) by providing a high-throughput, S3-compatible object store for application data.

**Architecture highlights:**
- 3× Master pods (Raft consensus on control-plane nodes) + 3× Filer pods + 4× Volume pods (one per node)
- Filer metadata stored in MariaDB Galera via ProxySQL — all three filers share a consistent namespace
- `replication=001`: 2 copies of every object on different volume servers
- No Longhorn overhead — all pods use `hostPath` local NVMe for maximum I/O

**S3 endpoint:** `192.168.4.208:8333` (MetalLB LoadBalancer)

**Measured throughput** (ARM Rockchip, boto3 persistent connections):

| Object Size | Upload | Download |
|---|---|---|
| 4 KB | ~100 ops/s | ~174 ops/s |
| 1 MB | ~42 MB/s | ~131 MB/s |
| 32 MB | ~63 MB/s | ~88 MB/s |

Full installation steps, Helm values, known bootstrap failures, and load-test results are documented in **[seaweedfs/README.md](seaweedfs/README.md)**.

---

## Hardware References

- [Turing Pi 2.5 board](https://turingpi.com/product/turing-pi-2-5/)
- [Turing RK1 compute module (16 GB)](https://turingpi.com/product/turing-rk1/?attribute_ram=16+GB)
- [Ubuntu for Turing RK1 (Joshua Riek)](https://joshua-riek.github.io/ubuntu-rockchip-download/boards/turing-rk1.html)
- [K3s documentation](https://docs.k3s.io/)
- [Longhorn documentation](https://longhorn.io/docs/)

---

<div align="center">

*Built and documented by a network/systems architect with too many nodes and not enough rack space.*

</div>

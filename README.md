<div align="center">

# Turing Pi 2.5 — ARM64 Kubernetes Home Lab

### A fully documented HA K3s cluster built on four RK1 compute modules

4× RK1 (RK3588) • 32 GB RAM per node • 1 TB NVMe per node • Ubuntu 24.04

K3s • Embedded etcd • Dual-Stack IPv4/IPv6 • Longhorn • MetalLB • Rancher

</div>

---

## Overview

This repository documents the build-out of a high-availability Kubernetes cluster (K3) on a [Turing Pi 2.5](https://turingpi.com/product/turing-pi-2-5/) board using four [RK1 compute modules](https://turingpi.com/product/turing-rk1/?attribute_ram=16+GB). The project covers everything from initial OS flashing through cluster deployment, storage, networking, observability, security hardening, and real-world benchmark results — with a growing library of automation scripts and expanded use cases.

The goal is a complete, reproducible reference for anyone running ARM64 Kubernetes on Turing Pi hardware, whether for home lab learning, edge computing, or low-power always-on services.

**Total cluster specs at a glance:**

| | |
|---|---|
| **Nodes** | 4× Turing RK1 (3 server(HA) + 1 worker) |
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
┌─────────────────────────────────────────────────────┐
│                 Turing Pi 2.5 Board                 │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│  │ k3-node1 │  │ k3-node2 │  │ k3-node3 │           │
│  │  Server  │  │  Server  │  │  Server  │           │
│  │  + etcd  │  │  + etcd  │  │  + etcd  │           │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘           │
│       └─────────────┴─────────────┘                 │
│                     │                               │
│              1 Gbps Backplane                       │
│                     │                               │
│             ┌───────┴──────┐                        │
│             │   k3-node4   │                        │
│             │    Worker    │                        │
│             └──────────────┘                        │
└─────────────────────────────────────────────────────┘
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

- **~$1,000** for a complete 4-node HA cluster with 128 GB RAM and 4 TB NVMe
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
4. **[OpenClaw guide](Installing_OpenClaw_on_your_TuringPi_RK1_Kubernetes_cluster_with_a_Discord_front_end.md)** — Deploy an AI assistant as your first real workload

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

## Hardware References

- [Turing Pi 2.5 board](https://turingpi.com/product/turing-pi-2-5/)
- [Turing RK1 compute module](https://turingpi.com/product/turing-rk1/)
- [Ubuntu for Turing RK1 (Joshua Riek)](https://joshua-riek.github.io/ubuntu-rockchip-download/boards/turing-rk1.html)
- [K3s documentation](https://docs.k3s.io/)
- [Longhorn documentation](https://longhorn.io/docs/)

---

<div align="center">

*Built and documented by a network/systems architect with too many nodes and not enough rack space.*

</div>

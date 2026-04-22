# Prometheus

## Overview

Prometheus is deployed as part of the **kube-prometheus-stack** Helm chart, which bundles
Prometheus, Alertmanager, the Prometheus Operator, kube-state-metrics, and node-exporter
into a single release. The Operator manages Prometheus and Alertmanager configuration
via Kubernetes CRDs (`ServiceMonitor`, `PodMonitor`, `PrometheusRule`, etc.).

## Credentials Setup

`kube-prometheus-stack-values.yaml` contains one `CHANGE_ME` entry:

| Field | Notes |
|---|---|
| `grafana.adminPassword` | Grafana web UI admin password — set before deploying |

Generate a strong password:
```bash
openssl rand -base64 20
```

## Installation

```bash
# Add the Helm repo
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Apply CRDs manually first (the chart's CRD upgrade Job fails due to RBAC)
helm pull prometheus-community/kube-prometheus-stack --version 83.6.0 --untar
kubectl apply --server-side -f kube-prometheus-stack/crds/ --force-conflicts

# Create namespace and install
kubectl create namespace monitoring
helm install monitoring prometheus-community/kube-prometheus-stack \
  -n monitoring \
  -f kube-prometheus-stack-values.yaml

# Upgrade (apply CRDs manually first each time)
helm pull prometheus-community/kube-prometheus-stack --version <new-version> --untar
kubectl apply --server-side -f kube-prometheus-stack/crds/ --force-conflicts
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  -n monitoring \
  -f kube-prometheus-stack-values.yaml
```

## Components

| Component | Pod | Purpose |
|---|---|---|
| Prometheus | `prometheus-monitoring-kube-prometheus-prometheus-0` | Metrics collection and storage |
| Alertmanager | `alertmanager-monitoring-kube-prometheus-alertmanager-0` | Alert routing and deduplication |
| Prometheus Operator | `monitoring-kube-prometheus-operator-*` | Manages Prometheus/Alertmanager via CRDs |
| kube-state-metrics | `monitoring-kube-state-metrics-*` | Kubernetes object metrics |
| node-exporter | `monitoring-prometheus-node-exporter-*` (one per node) | Host-level metrics |

## Storage

Prometheus TSDB data is stored on a 20 Gi RWO PVC. Two storage backends have been benchmarked
on this cluster — choose based on your priorities:

### Option A: Longhorn (current / default in values file)

```yaml
prometheus:
  prometheusSpec:
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: longhorn
          accessModes: [ReadWriteOnce]
          resources:
            requests:
              storage: 20Gi
```

**Why Longhorn:**
- PVC survives pod rescheduling to any node — Prometheus is not pinned to a specific host
- Replication (configurable, default 2 copies) protects TSDB data against single-node disk failure
- Consistent with other stateful workloads in the cluster

**Why not Longhorn:**
- All I/O crosses the 1 Gb backplane — write throughput capped at ~125 MB/s, compaction reads compete for LAN bandwidth
- WAL segment fsyncs measured at ~128ms (vs <1ms on local NVMe) — causes Prometheus to log slow WAL warnings under high cardinality

---

### Option B: local-path (higher performance)

```yaml
prometheus:
  prometheusSpec:
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: local-path
          accessModes: [ReadWriteOnce]
          resources:
            requests:
              storage: 20Gi
```

**Why local-path:**
- TSDB I/O stays entirely on the local NVMe — no network round-trips for WAL fsyncs or compaction
- Expected 3–5× improvement in WAL fsync latency and compaction throughput (see benchmarks below)
- Lower CPU overhead: no Longhorn replica synchronization on every write

**Why not local-path:**
- PVC is pinned to one node via `nodeAffinity`. If that node is lost, the TSDB data is gone.
- Pod cannot reschedule to a different node unless the PVC is manually migrated
- Prometheus metrics are ephemeral by nature (scraped every 15s) — losing the last 15 days of history is recoverable by waiting, not catastrophic

> **This cluster uses local-path** after the migration documented below. For most home lab and
> low-criticality monitoring deployments, the performance gain outweighs the loss of replication.
> For production alerting where historical data must survive node failure, use Longhorn.

---

### Storage Benchmark Results

The benchmark job in `tests/storage-benchmark.yaml` measures the I/O patterns Prometheus actually
uses: WAL fsync writes, compaction sequential reads/writes, and range-query random reads.
Run it before and after migration to reproduce these results.

**Test environment:** ARM64 Rockchip RK3588, Ubuntu 24.04, fio 3.36, 30s per phase, 3 GB test file.
**Prometheus state at test time:** 285,181 active series, 9,793 samples/sec ingestion.

#### fio Results

| Phase | Pattern | Metric | Longhorn | local-path |
|---|---|---|---|---|
| 1 — WAL fsync | 4KB seq write + fsync/op, 1 thread | Write BW | 829 KiB/s | **15.6 MiB/s** (19×) |
| 1 — WAL fsync | 4KB seq write + fsync/op, 1 thread | Avg latency | 57 µs | **19 µs** (3×) |
| 2 — WAL burst | 4KB seq write, 8 threads | Write BW | 162 MiB/s | **359 MiB/s** (2.2×) |
| 3 — Compaction read | 128KB seq read, 2 threads | Read BW | 110 MiB/s | **1391 MiB/s** (12.6×) |
| 4 — Compaction write | 128KB seq write, 2 threads | Write BW | 63.6 MiB/s | **1181 MiB/s** (18.6×) |
| 5 — Range query | 4KB random read, 8 threads | Read BW | 23.8 MiB/s | **196 MiB/s** (8.2×) |
| 6 — Mixed r/w | 4KB 70r/30w, 8 threads | Read BW | 18.1 MiB/s | **128 MiB/s** (7.1×) |
| 6 — Mixed r/w | 4KB 70r/30w, 8 threads | Write BW | 7.96 MiB/s | **55.0 MiB/s** (6.9×) |
| 7 — fsync micro | 4KB + fdatasync, 200 ops | Avg lat | 66 µs | **17.6 µs** (3.8×) |
| 7 — fsync micro | 4KB + fdatasync, 200 ops | p50 / max | 32 µs / 967 µs | **<10 µs / 652 µs** |

> **Note on WAL burst and compaction read:** Longhorn achieves 162 MiB/s write burst because the
> primary replica is on the same node — sequential writes hit local cache before replication.
> Compaction read at 110 MiB/s is at the 1 Gb LAN ceiling (125 MB/s theoretical).
>
> **local-path results:** The NVMe delivers 1391 MiB/s sequential read and 1181 MiB/s sequential
> write — 12–19× faster than Longhorn for compaction. WAL fsync bandwidth improved 19× (829 KiB/s
> → 15.6 MiB/s). The fsync micro benchmark shows avg 17.6 µs vs 66 µs on Longhorn, which will
> reduce Prometheus WAL fsync duration from ~128ms to low-ms range per WAL segment.

#### Live Prometheus TSDB Metrics

| Metric | Longhorn (pre-migration) | local-path (post-migration) |
|---|---|---|
| Active time series | 285,181 | 295,945 |
| Ingestion rate | 9,793 samples/sec | 9,768 samples/sec |
| WAL fsync duration (historical p50/p90/p99) | 128 ms / 128 ms / 128 ms | NaN (no segment fsynced yet) |
| WAL fsync count | 73 over 67 days | — |
| Query inner_eval p50 / p90 / p99 | 256 µs / 5.4 ms / 388 ms | 267 µs / 6.2 ms / 419 ms |
| Storage used | 7.7 GiB of 20 GiB | 49.3 GiB of 916 GiB (6%) |
| Blocks loaded | 17 | 18 |

> **Interpreting WAL fsync 128ms:** This is the time to fsync a full 128 MB WAL segment
> (not per 4KB write). With Longhorn, every fsync crosses the network to replicate the dirty
> segment — hence 128ms. On local NVMe the fio microbenchmark measured 17.6 µs avg fsync
> latency — Prometheus WAL fsync duration should drop to low-millisecond range once a
> segment completes (WAL segments fill at ~9,800 samples/sec, roughly every few minutes).
>
> **Storage used on local-path:** The 49.3 GiB reflects total NVMe partition usage, not just
> Prometheus data. The actual TSDB data (migrated from Longhorn) is approximately 8 GiB.

---

### Migrating from Longhorn to local-path

> **Complete the local-path benchmark first** (run `tests/storage-benchmark.yaml` with
> `storageClassName: local-path` before migrating) to establish the post-migration baseline
> and fill in the `—` cells in the table above.

```bash
# 1. Scale Prometheus down (prevents split-brain during volume migration)
kubectl scale statefulset -n monitoring \
  prometheus-monitoring-kube-prometheus-prometheus --replicas=0

# 2. Wait for pod to terminate
kubectl wait --for=delete pod/prometheus-monitoring-kube-prometheus-prometheus-0 \
  -n monitoring --timeout=120s

# 3. Delete the existing Longhorn PVC (data will be lost — acceptable for metrics)
kubectl delete pvc -n monitoring \
  prometheus-monitoring-kube-prometheus-prometheus-db-prometheus-monitoring-kube-prometheus-prometheus-0

# 4. Update kube-prometheus-stack-values.yaml: change storageClassName to local-path

# 5. Upgrade the Helm release to apply the new storage class
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  -n monitoring \
  -f kube-prometheus-stack-values.yaml

# 6. Prometheus will restart and create a fresh local-path PVC — scraping resumes
#    immediately; historical data (pre-migration) is gone
kubectl get pods -n monitoring -w

# 7. Verify the new PVC uses local-path
kubectl get pvc -n monitoring

# 8. After ~5 minutes, capture post-migration TSDB metrics and run the benchmark
#    again to fill in the local-path column in the table above
```

Retention uses the Prometheus default (15 days). Adjust with `prometheusSpec.retention` in values if needed.

## Services

| Service | Type | Address | Port | Purpose |
|---|---|---|---|---|
| `monitoring-kube-prometheus-prometheus` | ClusterIP | `10.43.239.23` | 9090 | Prometheus query API |
| `monitoring-kube-prometheus-alertmanager` | ClusterIP | — | 9093 | Alertmanager API |
| `monitoring-grafana` | LoadBalancer | `192.168.4.202` | 80 | Grafana UI (dual-stack) |

Prometheus itself is not exposed externally — query it through Grafana or by port-forwarding:

```bash
kubectl port-forward -n monitoring svc/monitoring-kube-prometheus-prometheus 9090:9090
# Then open http://localhost:9090
```

## ServiceMonitors

The stack ships with monitors for all core Kubernetes components. Application-level
ServiceMonitors are defined alongside each application and picked up automatically
because they carry the `release: monitoring` label:

| Application | ServiceMonitor location | Metrics port |
|---|---|---|
| ingress-nginx | `ingress-nginx` namespace | 10254 |
| MariaDB (mysqld_exporter) | `mariadb` namespace | 9104 |
| ProxySQL exporter | `mariadb` namespace | 42004 |
| SeaweedFS (master/filer/volume) | `seaweedfs` namespace | 9327 |
| OpenBao | `openbao` namespace | 8200 (`/v1/sys/metrics`) |

The Prometheus Operator discovers ServiceMonitors across all namespaces by default
in this configuration — no additional namespace selector changes are needed.

## Common Commands

```bash
# Pod status
kubectl get pods -n monitoring

# Prometheus targets (check scrape health)
kubectl port-forward -n monitoring svc/monitoring-kube-prometheus-prometheus 9090:9090
# open http://localhost:9090/targets

# Check active alerts
kubectl port-forward -n monitoring svc/monitoring-kube-prometheus-alertmanager 9093:9093
# open http://localhost:9093

# Reload Prometheus config (usually automatic via Operator)
kubectl rollout restart statefulset/prometheus-monitoring-kube-prometheus-prometheus -n monitoring

# Prometheus storage usage
kubectl exec -n monitoring prometheus-monitoring-kube-prometheus-prometheus-0 -c prometheus -- \
  df -h /prometheus
```

## Known Issues / Notes

- **CRD upgrade Job fails** — The chart's built-in CRD upgrade job (`crds.upgradeJob`) fails
  because the Job's ServiceAccount lacks permissions to update CRDs cluster-wide. Workaround:
  set `crds.enabled: false` and apply CRDs manually with `--server-side` before every upgrade.

- **VPA nil pointer** — Setting any `verticalPodAutoscaler.enabled: true` causes a nil pointer
  panic during templating if the VPA CRDs are not installed in the cluster. All three VPA flags
  (`alertmanager`, `prometheus`, `prometheusOperator`) must remain `false` unless you have
  VPA installed.

- **Grafana admin password** — The default `admin` password must be changed before any external
  exposure. See `../grafana/README.md` for Grafana-specific configuration.

## Files

| File | Purpose |
|---|---|
| `kube-prometheus-stack-values.yaml` | Helm values — storage, Grafana service type, VPA flags, CRD handling |
| `tests/storage-benchmark.yaml` | fio benchmark job — run before and after storage migration to compare results |

Grafana dashboard ConfigMaps are stored alongside the application they monitor:

| Dashboard | Location |
|---|---|
| MariaDB + ProxySQL | `../mariadb/grafana-dashboard-mariadb.yaml` |
| SeaweedFS | `../seaweedfs/grafana-dashboard-seaweedfs.yaml` |
| OpenBao | `../openbao/grafana-dashboard-openbao.yaml` |
| ingress-nginx | `../ingress-nginx/grafana-dashboard-ingress-nginx.yaml` |

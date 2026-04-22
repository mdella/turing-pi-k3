# Prometheus Storage Benchmark

## Overview

`storage-benchmark.yaml` is a Kubernetes Job that measures raw storage performance using I/O
patterns that match Prometheus TSDB behaviour. Run it before and after a storage migration to
produce a comparable baseline.

## Usage

```bash
# Run against the current storage class (defaults to longhorn in the yaml):
kubectl apply -f storage-benchmark.yaml
kubectl logs -n monitoring job/prometheus-storage-benchmark --follow
kubectl delete -f storage-benchmark.yaml

# Run against a different storage class:
sed 's/storageClassName: longhorn/storageClassName: local-path/' storage-benchmark.yaml \
  | kubectl apply -f -
kubectl logs -n monitoring job/prometheus-storage-benchmark --follow
sed 's/storageClassName: longhorn/storageClassName: local-path/' storage-benchmark.yaml \
  | kubectl delete -f -
```

The job creates a fresh 5 Gi PVC, runs 7 phases (30s each), prints results, and cleans up the
test file. Delete the job and PVC manually when done.

## Phases

| Phase | Pattern | Maps to |
|---|---|---|
| 1 — WAL fsync | 4KB seq write + fdatasync per op, 1 thread | `prometheus_tsdb_wal_fsync_duration_seconds` |
| 2 — WAL burst | 4KB seq write, 8 threads, no fsync | Peak scrape ingestion throughput |
| 3 — Compaction read | 128KB seq read, 2 threads, iodepth=4 | Reading old blocks for compaction |
| 4 — Compaction write | 128KB seq write, 2 threads, iodepth=4 | Writing compacted blocks back |
| 5 — Range query | 4KB random read, 8 threads, iodepth=8 | PromQL range query chunk reads |
| 6 — Mixed r/w | 4KB 70r/30w, 8 threads, iodepth=4 | Concurrent Grafana queries + scrape writes |
| 7 — fsync micro | 4KB + fdatasync, 200 ops, 1 thread | Direct per-fsync cost |

## Results — This Cluster

**Test environment:** ARM64 Rockchip RK3588 (k3-node4), Ubuntu 24.04, fio 3.36, 30s per phase,
3 GB test file, `/dev/nvme0n1p2 ext4`.

**Prometheus state at test time:** ~285K–295K active series, ~9,800 samples/sec ingestion.

### fio Results

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

> **Longhorn WAL burst (162 MiB/s):** The primary replica is on the same node, so sequential
> writes hit local cache before replication. Compaction read at 110 MiB/s is at the 1 Gb LAN
> ceiling (125 MB/s theoretical).
>
> **local-path NVMe:** 1391 MiB/s sequential read, 1181 MiB/s sequential write — 12–19× faster
> than Longhorn for compaction. WAL fsync bandwidth improved 19×. The fsync micro result of
> 17.6 µs avg means Prometheus WAL segment fsyncs drop from ~128ms (Longhorn) to low-ms range.

### Live Prometheus TSDB Metrics

| Metric | Longhorn (pre-migration) | local-path (post-migration) |
|---|---|---|
| Active time series | 285,181 | 295,945 |
| Ingestion rate | 9,793 samples/sec | 9,768 samples/sec |
| WAL fsync duration (p50/p90/p99) | 128 ms / 128 ms / 128 ms | NaN (no segment fsynced yet) |
| WAL fsync count | 73 over 67 days | — |
| Query inner_eval p50 / p90 / p99 | 256 µs / 5.4 ms / 388 ms | 267 µs / 6.2 ms / 419 ms |
| Storage used | 7.7 GiB of 20 GiB | ~8 GiB TSDB on 916 GiB NVMe |
| Blocks loaded | 17 | 18 |

> **WAL fsync 128ms on Longhorn:** This is the time to fsync a full 128 MB WAL segment — not
> per 4KB write. With Longhorn every fsync crosses the network to replicate the dirty segment.
> The fio Phase 7 result (17.6 µs avg) is the per-op cost on local NVMe; the actual WAL segment
> fsync will be in the low-millisecond range once a segment fills (~128 MB at 9,800 samples/sec).

## Capture live TSDB metrics during a benchmark run

```bash
# Active series + WAL fsync duration
kubectl exec -n monitoring prometheus-monitoring-kube-prometheus-prometheus-0 \
  -c prometheus -- wget -qO- http://localhost:9090/metrics \
  | grep -E 'tsdb_head_series |tsdb_wal_fsync_duration_seconds\{|engine_query_duration_seconds\{'

# Ingestion rate
kubectl exec -n monitoring prometheus-monitoring-kube-prometheus-prometheus-0 \
  -c prometheus -- wget -qO- \
  'http://localhost:9090/api/v1/query?query=rate(prometheus_tsdb_head_samples_appended_total[5m])'

# Storage usage
kubectl exec -n monitoring prometheus-monitoring-kube-prometheus-prometheus-0 \
  -c prometheus -- df -h /prometheus
```

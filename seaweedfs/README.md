# SeaweedFS

## Overview

SeaweedFS is a distributed object storage system deployed in HA mode across
the k3s cluster. It provides S3-compatible storage, a POSIX-like filer
interface, and scales horizontally across all 4 nodes.

## Credentials Setup

Three files contain `CHANGE_ME` placeholders that must be filled in before applying:

| File | Field | Notes |
|---|---|---|
| `seaweedfs-values.yaml` | `WEED_MYSQL_PASSWORD` | seaweedfs DB user password — must match `mariadb-galera.yaml` and `proxysql.yaml` |
| `s3-config.yaml` | `accessKey` / `secretKey` | S3 credentials for the admin identity — used by all S3 clients |
| `tests/test-s3.yaml` | `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Must match `s3-config.yaml` |
| `tests/loadtest.yaml` | `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Must match `s3-config.yaml` |
| `tests/loadtest-boto3.yaml` | `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Must match `s3-config.yaml` |

Generate S3 credentials:
```bash
openssl rand -hex 16   # 32-char access key
openssl rand -hex 24   # 48-char secret key
```

> The `WEED_MYSQL_PASSWORD` must be **identical** in `seaweedfs-values.yaml`, `../mariadb/mariadb-galera.yaml`, and `../proxysql/proxysql.yaml`.

## Architecture

```
                    SeaweedFS Cluster
                    
  Clients (S3, POSIX, HTTP)
           |
    [ Filer × 3 ]          ← metadata layer, nodes 1-3
    (MariaDB backend)       ← filer metadata in MariaDB via ProxySQL
           |
    [ Master × 3 ]         ← Raft consensus, nodes 1-3
           |
  +--------+--------+--------+
  |        |        |        |
[Vol]    [Vol]    [Vol]    [Vol]   ← data layer, all 4 nodes
node1    node2    node3    node4
```

## Components

| Component | Replicas | Nodes | Role |
|---|---|---|---|
| Master | 3 | nodes 1-3 (control-plane) | Raft leader election, volume assignment |
| Filer | 3 | nodes 1-3 (control-plane) | File namespace, metadata (stored in MariaDB) |
| Volume | 4 | all nodes | Actual blob/object storage |

## Storage Layout

All components use `hostPath` local storage for maximum I/O performance.
SeaweedFS replication (`001` = 2 copies on different servers) handles
data redundancy at the application layer — no Longhorn overhead.

| Component | Host Path | Notes |
|---|---|---|
| Master data | `/data/seaweedfs/master` | Raft state, volume assignments |
| Master logs | `/data/seaweedfs/master-logs` | |
| Filer data | `/data/seaweedfs/filer` | Local cache only (metadata in MariaDB) |
| Filer logs | `/data/seaweedfs/filer-logs` | |
| Volume data | `/data/seaweedfs/volume` | All blob data, one dir per node |
| Volume logs | `/data/seaweedfs/volume-logs` | |

## Replication

`replicationPlacement: "001"` — 2 copies of each file stored on different
volume servers in the same rack. With 4 volume nodes, any single node failure
is survivable without data loss.

## Filer Metadata Backend

Filer metadata is stored in **MariaDB** (not LevelDB2) so all 3 filer
replicas share a single consistent view of the namespace. Connection is via
ProxySQL for pooling and Galera-aware failover:

```
Filer → proxysql.mariadb.svc.cluster.local:6033 → MariaDB Galera
```

| Setting | Value |
|---|---|
| Host | `proxysql.mariadb.svc.cluster.local` |
| Port | `6033` |
| Database | `seaweedfs` |
| User | `seaweedfs` |
| Password | In `seaweedfs-values.yaml` (`WEED_MYSQL_PASSWORD`) |

## Node Targeting

- **Master + Filer**: `nodeSelector: node-role.kubernetes.io/control-plane: "true"` — pins to k3-node1, k3-node2, k3-node3
- **Volume servers**: no nodeSelector — anti-affinity spreads one pod per node across all 4

## Installation

```bash
# Namespace
kubectl create namespace seaweedfs

# Install
helm install seaweedfs seaweedfs/seaweedfs \
  -n seaweedfs \
  -f seaweedfs-values.yaml

# Upgrade
helm upgrade seaweedfs seaweedfs/seaweedfs \
  -n seaweedfs \
  -f seaweedfs-values.yaml
```

## Common Commands

```bash
# Cluster status
kubectl get pods -n seaweedfs -o wide

# Master status (Raft leader)
kubectl exec -n seaweedfs seaweedfs-master-0 -- weed master.info

# Filer status
kubectl get svc -n seaweedfs

# Volume server status
kubectl exec -n seaweedfs seaweedfs-master-0 -- weed shell -master=localhost:9333 volume.list

# Check MariaDB filer tables were created
kubectl exec -n mariadb mariadb-galera-0 -c mariadb -- \
  mariadb -useaweedfs -p<YOUR_SEAWEEDFS_DB_PASSWORD> seaweedfs \
  -e "SHOW TABLES;"
```

## Testing

Two test suites cover cluster health and S3 compatibility. Both run as
Kubernetes Jobs in the `seaweedfs` namespace.

### Cluster Health Test

**File**: `tests/test-cluster.yaml`

Validates the SeaweedFS cluster components are up and functional.

```bash
kubectl apply -f tests/test-cluster.yaml
kubectl logs -n seaweedfs job/seaweedfs-test --follow
kubectl delete -f tests/test-cluster.yaml
```

### S3 Compatibility Test

**File**: `tests/test-s3.yaml`

**What it tests** (17 assertions):

| Section | Tests |
|---|---|
| 1. S3 endpoint reachable | `aws s3 ls` via S3 service at port 8333 |
| 2. Bucket create/list | Create timestamped bucket, verify it appears in listing |
| 3. Small object upload/download | PUT + GET 1 KB file, verify via md5sum |
| 4. Large object upload/download | PUT + GET 5 MB file, verify via md5sum |
| 5. Object list | List objects in bucket |
| 6. Metadata (HEAD) | HEAD request returns 200 |
| 7. Copy | Server-side copy between keys |
| 8. Multipart upload | Initiate, upload parts, complete, verify |
| 9. Presigned URL | Generate presigned GET, download via wget |
| 10. Multipart delete | DeleteObjects on multiple keys |
| 11. Cleanup | Delete bucket and all contents |

```bash
kubectl apply -f tests/test-s3.yaml
kubectl logs -n seaweedfs job/seaweedfs-s3-test --follow
kubectl delete -f tests/test-s3.yaml
```

> **Note**: Bucket names are timestamped (`swfs-test-<unix-ts>`) to avoid
> `BucketAlreadyExists` conflicts between test runs.

### S3 Load Test

**File**: `tests/loadtest.yaml`

Measures throughput across four workload phases using parallel bash workers.
Results are printed as a summary table at the end.

```bash
# Run (delete first if re-running — job names are not timestamped)
kubectl delete -f tests/loadtest.yaml 2>/dev/null; kubectl apply -f tests/loadtest.yaml
kubectl logs -n seaweedfs job/seaweedfs-loadtest --follow
kubectl delete -f tests/loadtest.yaml   # cleanup when done
```

**Baseline results** (2026-04-21, ARM Rockchip, local-path storage):

| Phase | Direction | ops/s | MB/s |
|---|---|---|---|
| 4KB × 500 obj, 10 workers | upload | 2 | <1 |
| 4KB × 500 obj, 10 workers | download | 2 | <1 |
| 1MB × 160 obj, 8 workers | upload | 2 | 2 |
| 1MB × 160 obj, 8 workers | download | 2 | 2 |
| 32MB × 20 obj, 4 workers | upload | — | 23 |
| 32MB × 20 obj, 4 workers | download | — | 45 |
| 1MB mixed r+w, 5+5 workers | read+write | 2 | 2 |

**Key finding**: Small and medium object performance is bottlenecked by the
filer → MariaDB metadata path (2 ops/s regardless of concurrency). Large object
throughput is network/disk bound at 23–45 MB/s, which is healthy for this
hardware. Watch the **ProxySQL Connection Pool** panels in the MariaDB Grafana
dashboard while the load test runs to observe the bottleneck in real time.

To improve small object performance: enable SeaweedFS filer metadata caching
(`leveldb2` local cache in front of MySQL) in `seaweedfs-values.yaml`.

### boto3 Load Test (persistent connections)

**File**: `tests/loadtest-boto3.yaml`

Uses Python boto3 with persistent urllib3 connection pools — one S3 client per
worker thread, running in a timed loop rather than spawning a process per
operation. This reflects real application S3 throughput. Reports ops/s, MB/s,
and p50/p95/p99 latency per phase. Phase 8 is a concurrency scaling sweep.

```bash
kubectl delete -f tests/loadtest-boto3.yaml 2>/dev/null; kubectl apply -f tests/loadtest-boto3.yaml
kubectl logs -n seaweedfs job/seaweedfs-loadtest-boto3 --follow
kubectl delete -f tests/loadtest-boto3.yaml
```

**Baseline results** (2026-04-21, ARM Rockchip, 30s per phase):

| Size | Direction | Workers | ops/s | MB/s | p50 lat | p99 lat |
|---|---|---|---|---|---|---|
| 4KB | upload | 8 | 107 | 0.4 | 70ms | 123ms |
| 4KB | download | 8 | 174 | 0.7 | 38ms | 149ms |
| 1MB | upload | 8 | 42 | 41.6 | 194ms | 287ms |
| 1MB | download | 8 | 131 | 130.7 | 62ms | 115ms |
| 32MB | upload | 4 | 2 | 62.9 | 2081ms | 3658ms |
| 32MB | download | 4 | 3 | 87.5 | 1632ms | 2395ms |
| 1MB mixed write | 4 | 20 | 19.6 | — | 204ms | 297ms |
| 1MB mixed read | 4 | 100 | 100.5 | — | 38ms | 81ms |

**Concurrency scaling** (4KB writes, 15s each):

| Workers | ops/s | p50 | p99 |
|---|---|---|---|
| 1 | 28 | 35ms | 48ms |
| 4 | 78 | 51ms | 78ms |
| 8 | 98 | 72ms | 133ms |
| 16 | 130 | 107ms | 572ms (11 errors) |

**Key findings**:
- Persistent connections are **54× faster** than the CLI test for 4KB objects — the CLI test overhead was entirely process spawn + TLS handshake, not database or network.
- Small object throughput (~100 ops/s) is limited by filer → MariaDB metadata writes. Each S3 PUT costs more than one DB operation.
- Reads are ~1.6× faster than writes — reads only do a metadata lookup then stream from the volume server; writes go through filer→MariaDB write + Galera replication.
- 16 workers produces connection errors — 8 workers is the stable concurrency ceiling for this cluster.
- 32MB throughput (63/88 MB/s up/down) is network/disk bound — healthy for ARM local-path on 1Gb LAN.

## Files

| File | Purpose |
|---|---|
| `seaweedfs-values.yaml` | Helm values — topology, storage paths, MariaDB config |
| `seaweedfs-servicemonitors.yaml` | Prometheus ServiceMonitors for master/filer/volume (port 9327) |
| `tests/test-cluster.yaml` | Cluster health test suite |
| `tests/test-s3.yaml` | S3 compatibility test suite (17 assertions) |
| `tests/loadtest.yaml` | S3 load test — 4 phases, throughput summary table (CLI-based) |
| `tests/loadtest-boto3.yaml` | S3 load test — 8 phases, persistent connections, latency percentiles |

## Known Issues / Bootstrap Notes

- **`filemeta` table must be pre-created** before the filers start. SeaweedFS
  does not gracefully bootstrap its MySQL schema on first run — it crashes with
  `Error 1146: Table doesn't exist` instead of creating the table. Run this
  once before installing (or after wiping the DB):

  ```bash
  kubectl exec -n mariadb mariadb-galera-0 -c mariadb -- \
    mariadb -useaweedfs -p<password> seaweedfs -e "
      CREATE TABLE IF NOT EXISTS filemeta (
        dirhash   BIGINT NOT NULL,
        name      VARCHAR(766) NOT NULL,
        directory VARCHAR(4096),
        meta      LONGBLOB,
        PRIMARY KEY (dirhash, name)
      ) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;"
  ```

- The chart sets `WEED_MYSQL_USERNAME=null` and `WEED_MYSQL_PASSWORD=null` as
  defaults before our values. The later definitions in `extraEnvironmentVars`
  correctly override them (last env var wins in Linux containers).

- The `seaweedfs` DB user needs `ALL PRIVILEGES` on the `seaweedfs` database
  (not just the default limited grant from the operator). Applied manually:
  `GRANT ALL PRIVILEGES ON seaweedfs.* TO 'seaweedfs'@'%';`

## Dependencies

| Dependency | Location | Purpose |
|---|---|---|
| MariaDB Galera | `mariadb` namespace | Filer metadata store |
| ProxySQL | `mariadb` namespace | DB connection pooling + HA routing |

See `../mariadb/README.md` and `../proxysql/README.md`.

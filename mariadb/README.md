# MariaDB Galera Cluster

## Overview

A 3-node synchronous multi-master MariaDB Galera cluster deployed via the
`mariadb-operator`. All nodes can accept reads and writes simultaneously.
Replication is synchronous — a write is only acknowledged once committed on
all nodes.

## Credentials Setup

Before applying any manifests, set all passwords in `mariadb-galera.yaml`. Search for `CHANGE_ME` — there are three:

| Secret | File location | Used by |
|---|---|---|
| MariaDB root password | `mariadb-galera.yaml` → `mariadb-root` Secret | Root DB access |
| seaweedfs DB user password | `mariadb-galera.yaml` → `mariadb-seaweedfs` Secret | SeaweedFS filer + ProxySQL + SeaweedFS values |
| Metrics/monitoring user password | `mariadb-galera.yaml` → `mariadb-metrics-monitoring` Secret | Prometheus exporter sidecar |

Generate strong passwords:
```bash
openssl rand -hex 20   # generates a 40-char hex string
```

> **Cross-file dependency**: The seaweedfs DB user password must be **identical** in three places:
> 1. `mariadb-galera.yaml` (`mariadb-seaweedfs` Secret)
> 2. `../proxysql/proxysql.yaml` (`mysql_users` → `password`)
> 3. `../seaweedfs/seaweedfs-values.yaml` (`WEED_MYSQL_PASSWORD`)

The test file `tests/test-mariadb.yaml` has two additional `CHANGE_ME` entries for the ProxySQL radmin password and the MariaDB monitoring user password — set those to match `proxysql.yaml` and `mariadb-galera.yaml` before running tests.

The `mariadb-galera-values.yaml` file also contains `CHANGE_ME` placeholders — that file is the superseded Bitnami chart attempt kept for reference only and is not applied.

## Installation

| Component | Details |
|---|---|
| Operator chart | `mariadb-operator/mariadb-operator` v26.3.0 |
| CRDs chart | `mariadb-operator/mariadb-operator-crds` v26.3.0 |
| MariaDB image | `mariadb:11.4` (official Docker Hub) |
| Namespace | `mariadb` |

## Cluster Layout

| Pod | Node | PV | Path |
|---|---|---|---|
| `mariadb-galera-0` | k3-node3 | `mariadb-storage-0` | `/data/mariadb/storage` |
| `mariadb-galera-1` | k3-node2 | `mariadb-storage-1` | `/data/mariadb/storage` |
| `mariadb-galera-2` | k3-node1 | `mariadb-storage-2` | `/data/mariadb/storage` |

Nodes are pinned via the `mariadb-galera: "true"` label applied to k3-node1,
k3-node2, k3-node3. k3-node4 is excluded.

## Storage

- **Type**: `local-path` hostPath PVs — local disk I/O, no network overhead
- **Size**: 20Gi per node
- **Why not Longhorn**: Galera already provides synchronous replication at the
  DB layer. Using Longhorn on top would double-replicate every write.
- **PV affinity**: PVs are pre-created with `claimRef` and explicit
  `nodeAffinity` so the local-path provisioner cannot bind them to the wrong
  node. Defined in `mariadb-pvs.yaml`.
- **Galera config files**: stored inside the main data volume
  (`reuseStorageVolume: true`) to avoid a separate PVC with ownership issues.
- **Host directory ownership**: `/data/mariadb/storage` pre-created as
  `999:999` (mysql uid/gid) on each node via `kubectl debug node`.

## Services

| Service | Type | Address | Purpose |
|---|---|---|---|
| `mariadb-galera` | ClusterIP | `mariadb-galera.mariadb.svc.cluster.local:3306` | All nodes (round-robin) |
| `mariadb-galera-primary` | ClusterIP | `mariadb-galera-primary.mariadb.svc.cluster.local:3306` | Primary only |
| `mariadb-galera-secondary` | ClusterIP | `mariadb-galera-secondary.mariadb.svc.cluster.local:3306` | Replicas only |
| `mariadb-galera-internal` | Headless | `mariadb-galera-{0,1,2}.mariadb-galera-internal.mariadb.svc.cluster.local:3306` | Per-pod DNS for ProxySQL |

For in-cluster applications, ProxySQL at `proxysql.mariadb.svc.cluster.local:6033`
is the recommended single entry point — see `../proxysql/README.md`.

## Databases & Users

| Database | User | Password file |
|---|---|---|
| `seaweedfs` | `seaweedfs` | `secret/mariadb-seaweedfs` in `mariadb` namespace |

Root password is stored in `secret/mariadb-root` in the `mariadb` namespace.

## Files

| File | Purpose |
|---|---|
| `mariadb-galera.yaml` | MariaDB CRD manifest (cluster definition, secrets) |
| `mariadb-pvs.yaml` | Pre-created PVs with node affinity and claimRefs |
| `mariadb-galera-values.yaml` | Original Bitnami values attempt (superseded, kept for reference) |
| `tests/test-mariadb.yaml` | End-to-end test suite (21 assertions) |
| `tests/loadtest.yaml` | Load test — 7 phases, throughput summary table |

## Common Commands

```bash
# Cluster status
kubectl get mariadb -n mariadb

# Pod placement
kubectl get pods -n mariadb -o wide

# Connect as root
kubectl exec -it -n mariadb mariadb-galera-0 -c mariadb -- \
  mariadb -uroot -p$(kubectl get secret -n mariadb mariadb-root -o jsonpath='{.data.password}' | base64 -d)

# Check Galera cluster size and status
kubectl exec -n mariadb mariadb-galera-0 -c mariadb -- \
  mariadb -uroot -p<password> -e "SHOW STATUS LIKE 'wsrep_%';"

# Upgrade operator
helm upgrade mariadb-operator mariadb-operator/mariadb-operator -n mariadb
helm upgrade mariadb-operator-crds mariadb-operator/mariadb-operator-crds -n mariadb
```

## Testing

The test suite validates cluster health, Galera replication, ProxySQL routing,
and user access. Tests run as a Kubernetes Job in the `mariadb` namespace.

**File**: `tests/test-mariadb.yaml`

**What it tests** (21 assertions):

| Section | Tests |
|---|---|
| 1. ProxySQL reachable | `seaweedfs` user can connect via ProxySQL port 6033 |
| 2. Galera cluster health | `wsrep_cluster_size=3`, status=Primary, wsrep_ready/connected=ON |
| 3. All 3 nodes directly reachable | Direct connection to each pod headless DNS |
| 4. Write via ProxySQL | CREATE TABLE, INSERT, SELECT round-trip through ProxySQL |
| 5. Replication verified | Inserted row visible on all 3 nodes directly |
| 6. ProxySQL HG10/HG30 routing | Writer online in HG10, ≥2 readers online in HG30 |
| 7. Connection pool stats | `stats_mysql_connection_pool` accessible |
| 8. SeaweedFS filemeta table | `seaweedfs.filemeta` table exists |
| 9. Metrics user | `monitoring` user can connect to MariaDB directly |
| 10. Cleanup | Test row and table removed |

**Run**:

```bash
kubectl apply -f tests/test-mariadb.yaml
kubectl logs -n mariadb job/mariadb-test --follow
kubectl delete -f tests/test-mariadb.yaml   # cleanup
```

> **Note**: The mariadb-operator enables TLS with a self-signed certificate.
> The test uses `--ssl=FALSE` on all connections. This is expected — the operator
> manages its own cert and the client cannot verify it without the CA.

## Load Testing

**File**: `tests/loadtest.yaml`

7 phases covering raw insert throughput, ProxySQL routing overhead, read
throughput, mixed workload, transaction rate, Galera replication lag, and
query plan comparison (index vs full-table scan).

```bash
# Run (delete first if re-running)
kubectl delete -f tests/loadtest.yaml 2>/dev/null; kubectl apply -f tests/loadtest.yaml
kubectl logs -n mariadb job/mariadb-loadtest --follow
kubectl delete -f tests/loadtest.yaml   # cleanup when done
```

**Baseline results** (2026-04-21, ARM Rockchip, 3-node Galera):

| Phase | Result | Notes |
|---|---|---|
| Raw INSERT, direct (8 workers) | **666 rows/s** | Galera sync-write baseline |
| INSERT via ProxySQL (8 workers) | **571 rows/s** | ~14% ProxySQL overhead — healthy |
| SELECT via ProxySQL (8 workers) | **307 q/s** | CLI spawn cost dominates; persistent connections would be 5–10× higher |
| Mixed r/w via ProxySQL (5+5) | **333 ops/s** | Reads and writes compete for connection pool slots |
| Transactions via ProxySQL (5 workers) | **166 TPS** | Multi-stmt txns halve throughput vs single INSERTs |
| Index scan (worker_id) | **12 q/s** | CLI spawn overhead dominates for small result sets |
| Range scan (num BETWEEN) | **24 q/s** | Tighter range = better selectivity |
| Full-table scan (payload LIKE) | **~instant** | 7.5K rows fit entirely in InnoDB buffer pool |

**Key findings**:

- **Galera adds ~14% write overhead** vs direct — the sync certification cost across 3 nodes is minimal on this hardware.
- **No replication lag observed** — `wsrep_local_recv_queue=0` and `flow_control_paused≈0` on all 3 nodes after a 1,000-row bulk insert. The cluster is not stressed by this workload.
- **CLI spawn overhead dominates read benchmarks** — real application throughput using persistent connections (connection pools) will be significantly higher than the 307 q/s measured here.
- **SeaweedFS filer's 2 ops/s is not a MariaDB capacity issue** — MariaDB can sustain 571 writes/s. The bottleneck is SeaweedFS opening a new connection per metadata operation rather than pooling. Enabling the SeaweedFS filer's `leveldb2` local metadata cache would reduce round-trips to MariaDB.

## Known Issues / Notes

- After a full cluster restart (all 3 nodes down), Galera requires a bootstrap.
  The operator handles this automatically via the recovery process.
- The `mariadb-operator` uses `OnDelete` StatefulSet strategy — pods must be
  deleted manually to pick up config changes to the CRD.
- OpenBao auto-unseal is not configured — unrelated but noted here since
  MariaDB could back it in future.

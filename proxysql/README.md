# ProxySQL

## Overview

ProxySQL is a high-performance MySQL/MariaDB protocol proxy deployed in front
of the MariaDB Galera cluster. It provides:

- **Single connection endpoint** for both in-cluster and external clients
- **Galera-aware routing** — automatically detects which nodes are healthy
  writers vs. readers; fails over without application changes
- **Read/write splitting** — `SELECT` queries route to reader hostgroup,
  writes route to the active writer
- **Connection pooling** — reduces connection overhead for applications
- **2 replicas** spread across nodes — proxy layer itself is HA

## Credentials Setup

`proxysql.yaml` contains three `CHANGE_ME` entries in the ConfigMap:

| Field | Location | Notes |
|---|---|---|
| ProxySQL admin/radmin password | `admin_credentials` line | Used by the admin interface and `proxysql-exporter.yaml` |
| Monitor user password | `monitor_password` | Must match a `proxysql_monitor` user created in MariaDB |
| seaweedfs application user password | `mysql_users` → `password` | Must match `mariadb-galera.yaml` and `seaweedfs-values.yaml` |

`proxysql-exporter.yaml` has one `CHANGE_ME` entry — the `proxysql-exporter-secret` password must match the `radmin` password in `proxysql.yaml`.

Generate strong passwords:
```bash
openssl rand -hex 16   # 32-char hex — suitable for all ProxySQL passwords
```

After editing, apply in order: `mariadb-galera.yaml` first (to create the DB users), then `proxysql.yaml`.

## Architecture

```
in-cluster apps          external clients
(SeaweedFS, Ghost)       (DBA tools, external apps)
        |                        |
  ClusterIP :6033         LoadBalancer :3306
  proxysql.mariadb               192.168.4.207
  .svc.cluster.local
        \                       /
         +------ProxySQL-------+
         (2 replicas, any node)
                   |
       +-----------+-----------+
       |           |           |
   pod-0        pod-1       pod-2
  k3-node3    k3-node2    k3-node1
   (writer    (backup     (backup
   HG 10)     HG 20)      HG 20)
```

## Hostgroup Routing

| Hostgroup | Role | Description |
|---|---|---|
| 10 | Writer | Active single writer (max_writers=1) |
| 20 | Backup writer | Promoted automatically if HG 10 node fails |
| 30 | Reader | All healthy nodes; receives `SELECT` traffic |
| 9999 | Offline | Nodes removed from rotation |

ProxySQL monitors `wsrep_local_state_comment` on each node every 2 seconds
and reclassifies nodes automatically.

## Query Routing Rules

| Rule | Pattern | Destination |
|---|---|---|
| 1 | `SELECT ... FOR UPDATE` | Writer (HG 10) — needs row lock |
| 2 | `SELECT ...` | Reader (HG 30) |
| — | Everything else | Writer (HG 10) default |

## Services

| Service | Type | Address | Port | Purpose |
|---|---|---|---|---|
| `proxysql` | ClusterIP | `proxysql.mariadb.svc.cluster.local` | 6033 | In-cluster MySQL traffic |
| `proxysql-external` | LoadBalancer | `192.168.4.207` | 3306 | External MySQL traffic |
| `proxysql-admin` | ClusterIP | `proxysql-admin.mariadb.svc.cluster.local` | 6032 | Admin interface (internal only) |

## Credentials

| User | Purpose | Password secret |
|---|---|---|
| `admin` / `radmin` | ProxySQL admin interface | Stored in `proxysql-config` ConfigMap |
| `proxysql_monitor` | Backend health monitoring | Stored in `proxysql-config` ConfigMap |
| `seaweedfs` | Application user | Proxied through to MariaDB |

> **Note**: Admin credentials are stored in the ConfigMap. For production,
> move them to a Kubernetes Secret and reference via env vars.

## Monitoring

A `proxysql_exporter` sidecar deployment scrapes the ProxySQL admin stats interface
and exposes Prometheus metrics on port 42004. These feed the **ProxySQL Connection Pool**
section of the MariaDB Grafana dashboard.

Key metrics:

| Metric | Description |
|---|---|
| `proxysql_connection_pool_conn_used` | Connections currently in use per backend |
| `proxysql_connection_pool_conn_free` | Free connections available per backend |
| `proxysql_connection_pool_conn_err` | Cumulative backend connection errors |
| `proxysql_connection_pool_queries` | Queries routed per backend |
| `proxysql_connection_pool_latency_us` | Average backend latency in microseconds |

```bash
# Check exporter is running
kubectl get pods -n mariadb -l app=proxysql-exporter

# Raw metrics
kubectl exec -n mariadb deploy/proxysql-exporter -- \
  wget -qO- http://localhost:42004/metrics | grep proxysql_connection_pool
```

## Files

| File | Purpose |
|---|---|
| `proxysql.yaml` | ConfigMap + Deployment + all Services |
| `proxysql-exporter.yaml` | Prometheus exporter deployment + ServiceMonitor |

## Common Commands

```bash
# Check ProxySQL pods
kubectl get pods -n mariadb -l app=proxysql -o wide

# Connect to ProxySQL admin interface
kubectl exec -it -n mariadb deploy/proxysql -- \
  mysql -h127.0.0.1 -P6032 -uadmin -p<YOUR_PROXYSQL_ADMIN_PASSWORD> --prompt='ProxySQL Admin> '

# Check backend server status
# (run inside admin interface)
SELECT hostgroup_id, hostname, status, ConnUsed, MaxConnUsed, Queries FROM stats_mysql_connection_pool;

# Check which node is the active writer
SELECT hostgroup_id, hostname, status FROM runtime_mysql_servers ORDER BY hostgroup_id;

# Reload config from disk (after editing ConfigMap + restarting pods)
kubectl rollout restart deployment/proxysql -n mariadb

# External connection (from outside cluster)
mysql -h 192.168.4.207 -P 3306 -useaweedfs -p<password> seaweedfs
```

## Updating Config

ProxySQL config lives in the `proxysql-config` ConfigMap. To apply changes:

```bash
kubectl edit configmap proxysql-config -n mariadb
kubectl rollout restart deployment/proxysql -n mariadb
```

## Testing

ProxySQL routing is covered by the MariaDB test suite in `../mariadb/tests/test-mariadb.yaml`.

Relevant sections:

| Test | What it verifies |
|---|---|
| Section 1 | `seaweedfs` user connects via ProxySQL port 6033 |
| Section 4 | Writes route through ProxySQL to MariaDB |
| Section 6 | HG10 has an online writer; HG30 has ≥2 readers |
| Section 7 | `stats_mysql_connection_pool` is accessible via admin |

```bash
kubectl apply -f ../mariadb/tests/test-mariadb.yaml
kubectl logs -n mariadb job/mariadb-test --follow
kubectl delete -f ../mariadb/tests/test-mariadb.yaml
```

> **Note**: The ProxySQL admin interface requires `--ssl=FALSE` when connecting
> remotely — the TLS certificate presented by the radmin interface cannot be
> verified by external clients. The test uses `--ssl=FALSE` for all connections.

## Notes

- `max_writers=1` keeps a single active writer even though Galera supports
  multi-master. This avoids write-set conflicts under high concurrency. Raise
  to 3 if your workload benefits from distributed writes.
- ProxySQL does not persist runtime changes (e.g. via admin SQL) across pod
  restarts — all config is sourced from the ConfigMap on startup.
- The admin interface (port 6032) is intentionally ClusterIP-only. Never
  expose it externally.

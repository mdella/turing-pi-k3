# Uptime Kuma

## Overview

Uptime Kuma is a self-hosted uptime monitoring tool with a clean web UI. It provides
status checks (HTTP, TCP, ping, DNS, etc.), incident history, and notification alerts
for services across the cluster and beyond.

## Access

| Detail | Value |
|---|---|
| URL | `http://192.168.4.209` |
| First-run | Create admin account on first visit (no default credentials) |

## Installation

```bash
kubectl apply -f uptime-kuma.yaml
```

## Configuration

No credentials to set in advance — Uptime Kuma prompts for an admin username and
password on first login.

## Monitors

Monitors are configured via the web UI. The table below documents what is currently
set up, including any non-obvious configuration choices.

### Cluster Nodes (ping)

| Monitor | Type | Target |
|---|---|---|
| k3-node1 | ping | 192.168.4.101 |
| k3-node2 | ping | 192.168.4.102 |
| k3-node3 | ping | 192.168.4.103 |
| k3-node4 | ping | 192.168.4.104 |

### Services

| Monitor | Type | Target | Notes |
|---|---|---|---|
| Ghost Blog | HTTP | `http://192.168.4.204` | |
| Grafana | HTTP | `http://192.168.4.202` | |
| Portainer | HTTP | `http://192.168.4.200:9000` | Port 9000 (HTTP); HTTPS is 9443 |
| ingress-nginx | HTTP | `http://192.168.4.201/healthz` | Root `/` returns 404 (no default backend); use `/healthz` |
| SeaweedFS S3 | HTTP | `http://192.168.4.208:8333` | S3 API is on 8333 not 80; accepts 403 (auth required but service is up) |
| ProxySQL | TCP port | 192.168.4.207:3306 | External port 3306 maps to internal container port 6033 |

### Monitoring Stack (internal cluster DNS)

| Monitor | Type | Target | Notes |
|---|---|---|---|
| Prometheus | HTTP | `http://monitoring-kube-prometheus-prometheus.monitoring:9090/-/healthy` | Not externally exposed |
| Alertmanager | HTTP | `http://monitoring-kube-prometheus-alertmanager.monitoring:9093/-/healthy` | Not externally exposed |

### OpenBao (split monitors)

OpenBao runs as a 3-node Raft cluster. A single check against the `openbao` Service
load-balances across all pods and cycles between 200 (active leader) and 429 (healthy
standby), making the uptime percentage meaningless. Two monitors are used instead:

| Monitor | Type | Target | Accepted codes | Notes |
|---|---|---|---|---|
| OpenBao (active leader) | HTTP | `http://openbao-active.openbao:8200/v1/sys/health` | 200 | Helm creates `openbao-active` svc pointing only to the current leader |
| OpenBao (standby nodes) | HTTP | `http://openbao-standby.openbao:8200/v1/sys/health` | 429 | 429 = healthy standby; red means nodes are down or sealed |

During a leader election both monitors stay green — Kubernetes updates the endpoint
selectors automatically as the new leader is elected.

### Not monitored

| Service | Reason |
|---|---|
| openclaw (Discord bot) | Binds to `127.0.0.1:18789` only — no reachable HTTP endpoint. Needs a push monitor with a heartbeat call added to the bot code. See todo list. |

## MariaDB individual node monitors

The three Galera nodes are monitored by TCP port check against their internal StatefulSet
DNS names rather than through ProxySQL, so a single dead node is visible even if ProxySQL
is still routing around it:

| Monitor | Hostname |
|---|---|
| MariaDB galera-0 | `mariadb-galera-0.mariadb-galera-internal.mariadb.svc.cluster.local:3306` |
| MariaDB galera-1 | `mariadb-galera-1.mariadb-galera-internal.mariadb.svc.cluster.local:3306` |
| MariaDB galera-2 | `mariadb-galera-2.mariadb-galera-internal.mariadb.svc.cluster.local:3306` |

## Storage

Data (SQLite database, config) is stored on a 2 Gi local-path PVC. The deployment
uses `strategy: Recreate` to ensure the single replica fully stops before the new
one starts (required for SQLite write safety).

## Common Commands

```bash
# Pod status
kubectl get pods -n uptime-kuma

# Logs
kubectl logs -n uptime-kuma deployment/uptime-kuma

# Restart (picks up any image updates)
kubectl rollout restart deployment/uptime-kuma -n uptime-kuma

# Query monitor config directly (useful if UI is unavailable)
kubectl exec -n uptime-kuma deployment/uptime-kuma -- sqlite3 /app/data/kuma.db \
  "SELECT name, type, url, hostname, port, accepted_statuscodes_json FROM monitor ORDER BY name;"
```

## Adding monitors via SQLite

Uptime Kuma v2 uses Socket.IO for its API — the HTTP `/api/v1/...` paths return the
SPA shell rather than JSON. The most reliable way to add monitors programmatically
(or when the UI is unavailable) is direct SQLite access:

```bash
# Connect to the database
kubectl exec -n uptime-kuma deployment/uptime-kuma -- sqlite3 /app/data/kuma.db

# Example: add an HTTP monitor
INSERT INTO monitor (name, type, url, interval, maxretries, retry_interval, active, accepted_statuscodes_json, user_id, created_date)
VALUES ('My Service', 'http', 'http://my-service.namespace:8080/health', 60, 1, 20, 1, '["200-299"]', 1, datetime('now'));

# Example: add a TCP port monitor
INSERT INTO monitor (name, type, hostname, port, interval, maxretries, retry_interval, active, accepted_statuscodes_json, user_id, created_date)
VALUES ('My DB', 'port', '192.168.4.x', 3306, 60, 1, 20, 1, '["200-299"]', 1, datetime('now'));

# Example: add a ping monitor
INSERT INTO monitor (name, type, hostname, interval, maxretries, retry_interval, active, accepted_statuscodes_json, user_id, created_date)
VALUES ('My Node', 'ping', '192.168.4.x', 60, 1, 20, 1, '["200-299"]', 1, datetime('now'));
```

After any direct SQLite change, restart the deployment for Uptime Kuma to reload:

```bash
kubectl rollout restart deployment/uptime-kuma -n uptime-kuma
```

## Files

| File | Purpose |
|---|---|
| `uptime-kuma.yaml` | Namespace, PVC, Deployment, and LoadBalancer Service |

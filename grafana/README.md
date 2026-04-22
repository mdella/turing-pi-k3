# Grafana

## Overview

Grafana is deployed as part of the **kube-prometheus-stack** Helm release (see
`../prometheus/README.md` for installation). It is exposed externally via a
MetalLB LoadBalancer and uses Prometheus as its primary data source, which is
auto-configured by the chart.

## Credentials Setup

The Grafana admin password is set in `../prometheus/kube-prometheus-stack-values.yaml`
under `grafana.adminPassword`. It must be changed from the default before any
external exposure:

```bash
# Update the password via Grafana API (after first login)
curl -X PUT http://admin:<current-password>@192.168.4.202/api/user/password \
  -H "Content-Type: application/json" \
  -d '{"oldPassword":"<current>","newPassword":"<new>","confirmNew":"<new>"}'

# Or via the UI: Profile → Change Password
```

## Access

| Detail | Value |
|---|---|
| External URL | `http://192.168.4.202` (MetalLB LoadBalancer, dual-stack) |
| Default username | `admin` |
| Default password | See `../prometheus/kube-prometheus-stack-values.yaml` |
| Prometheus data source | Auto-configured by chart → `http://monitoring-kube-prometheus-prometheus:9090` |

## Dashboard Provisioning

Grafana dashboards are provisioned as **ConfigMaps** in the `monitoring` namespace.
The Grafana sidecar (`grafana-sc-dashboard`) watches for ConfigMaps with the label
`grafana_dashboard: "1"` and hot-loads them without a pod restart.

To apply a dashboard:
```bash
kubectl apply -f <dashboard-configmap.yaml>
# Dashboard appears in Grafana within ~30 seconds — no restart needed
```

To remove a dashboard:
```bash
kubectl delete -f <dashboard-configmap.yaml>
```

## Dashboards

Dashboards are stored alongside the application they monitor. All use the
`monitoring` namespace and the `grafana_dashboard: "1"` label for auto-provisioning.

| Dashboard | File | Covers |
|---|---|---|
| **MariaDB + ProxySQL** | `../mariadb/grafana-dashboard-mariadb.yaml` | Galera cluster health, query throughput, ProxySQL connection pool, replication lag |
| **SeaweedFS** | `../seaweedfs/grafana-dashboard-seaweedfs.yaml` | Master/filer/volume health, S3 request rates, storage utilization |
| **OpenBao** | `../openbao/grafana-dashboard-openbao.yaml` | Seal status, token activity, request latency, Raft peer health |
| **ingress-nginx** | `../ingress-nginx/grafana-dashboard-ingress-nginx.yaml` | Request rate, error rate, latency percentiles, upstream response times |

### Apply all dashboards at once

```bash
kubectl apply -f ../mariadb/grafana-dashboard-mariadb.yaml
kubectl apply -f ../seaweedfs/grafana-dashboard-seaweedfs.yaml
kubectl apply -f ../openbao/grafana-dashboard-openbao.yaml
kubectl apply -f ../ingress-nginx/grafana-dashboard-ingress-nginx.yaml
```

## Built-in Dashboards

The kube-prometheus-stack chart ships with dashboards for all core Kubernetes
components — these are pre-loaded and require no manual action:

| Category | Dashboards included |
|---|---|
| Kubernetes cluster | Node, namespace, pod, and workload resource usage |
| etcd | Leader elections, proposals, disk sync duration |
| CoreDNS | Query rate, cache hits, latency |
| API server | Request rate, error rate, latency, audit |
| Scheduler / controller-manager | Scheduling latency, queue depth, work duration |
| Alertmanager | Alert groups, notification pipeline |
| Prometheus | TSDB size, scrape duration, rule evaluation |
| Node exporter | Per-node CPU, memory, disk I/O, network |

## Common Commands

```bash
# Pod status
kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana

# Grafana logs (useful if dashboards aren't loading)
kubectl logs -n monitoring -l app.kubernetes.io/name=grafana -c grafana --tail=50

# Sidecar logs (dashboard discovery)
kubectl logs -n monitoring -l app.kubernetes.io/name=grafana -c grafana-sc-dashboard --tail=30

# List provisioned dashboard ConfigMaps
kubectl get configmap -n monitoring -l grafana_dashboard=1

# Port-forward (if LoadBalancer is unavailable)
kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80
# open http://localhost:3000

# Reset admin password via kubectl exec
kubectl exec -n monitoring deploy/monitoring-grafana -c grafana -- \
  grafana-cli admin reset-admin-password <new-password>
```

## Notes

- Grafana state (dashboards created via UI, user accounts, annotations) is stored in
  an in-pod SQLite database — it is **not persisted** across pod restarts by default
  in this deployment. Dashboards defined as ConfigMaps (all of ours) are re-provisioned
  automatically; hand-created dashboards will be lost on restart.
- To persist UI-created dashboards, add a PVC for Grafana storage in the Helm values:
  `grafana.persistence.enabled: true`.
- The Prometheus data source retention window is 15 days (Prometheus default). Queries
  for ranges beyond that will return no data unless retention has been extended.

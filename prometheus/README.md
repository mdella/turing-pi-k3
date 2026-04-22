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

Prometheus TSDB data is stored on a **20 Gi Longhorn RWO PVC**:

```
prometheus-monitoring-kube-prometheus-prometheus-db-prometheus-monitoring-kube-prometheus-prometheus-0
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

Grafana dashboard ConfigMaps are stored alongside the application they monitor:

| Dashboard | Location |
|---|---|
| MariaDB + ProxySQL | `../mariadb/grafana-dashboard-mariadb.yaml` |
| SeaweedFS | `../seaweedfs/grafana-dashboard-seaweedfs.yaml` |
| OpenBao | `../openbao/grafana-dashboard-openbao.yaml` |
| ingress-nginx | `../ingress-nginx/grafana-dashboard-ingress-nginx.yaml` |

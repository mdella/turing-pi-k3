# OpenBao

## Overview

OpenBao is an open-source fork of HashiCorp Vault, deployed as a 3-node HA
cluster using Raft consensus. It provides secrets management, dynamic
credentials, and Kubernetes auth for workloads running in the cluster.

## Installation

| Component | Details |
|---|---|
| Chart | `openbao/openbao` |
| Image | `openbao/openbao:2.5.2` |
| Namespace | `openbao` |
| Storage | Raft integrated (BoltDB), `hostPath` on each pod's node |

## Architecture

3-node Raft cluster — one active node, two standbys. Leader election is
automatic. The `openbao-active` service always resolves to the current leader.

```
openbao-0   openbao-1   openbao-2
(active or standby, elected via Raft)
        |
 openbao-active.openbao.svc.cluster.local:8200   ← always leader
 openbao-internal.openbao.svc.cluster.local       ← per-pod headless DNS
```

## Services

| Service | Type | Address | Port | Purpose |
|---|---|---|---|---|
| `openbao-active` | ClusterIP | `openbao-active.openbao.svc.cluster.local` | 8200 | Current leader only |
| `openbao` | ClusterIP | `openbao.openbao.svc.cluster.local` | 8200 | Any node (round-robin) |
| `openbao-internal` | Headless | `openbao-{0,1,2}.openbao-internal.openbao.svc.cluster.local` | 8200 | Per-pod DNS |

## Auth Methods

| Method | Purpose |
|---|---|
| `token/` | Root token, initial access |
| `kubernetes/` | Pod identity — allows in-cluster workloads to authenticate |

## Unseal

OpenBao uses **Shamir secret sharing** (5 shares, threshold 3). Auto-unseal
is not configured. After any cluster reboot, all pods will start sealed and
require manual key entry:

```bash
# Check seal status
kubectl exec -n openbao openbao-0 -- bao status

# Unseal each pod (repeat for pod-1, pod-2)
kubectl exec -it -n openbao openbao-0 -- bao operator unseal
```

> **Important**: The StatefulSet uses `OnDelete` update strategy. After a
> `helm upgrade`, pods must be deleted manually to pick up new config. Also,
> `OrderedReady` policy means pod-1 and pod-2 won't be scheduled until pod-0
> is Ready (unsealed).

## Monitoring

Metrics are exposed at `/v1/sys/metrics?format=prometheus` on port 8200.
Unauthenticated access is enabled via the `telemetry` config stanza.

OpenBao exports metrics with the `vault_` prefix (Vault-compatible telemetry).

- **ServiceMonitor**: `openbao-servicemonitor.yaml`
- **Grafana dashboard**: `grafana-dashboard-openbao.yaml` (apply to `monitoring` namespace)

## Files

| File | Purpose |
|---|---|
| `openbao-values.yaml` | Helm values — raft config, telemetry, listener |
| `openbao-servicemonitor.yaml` | Prometheus ServiceMonitor (port 8200, path `/v1/sys/metrics`) |
| `grafana-dashboard-openbao.yaml` | Grafana dashboard ConfigMap (monitoring namespace) |
| `tests/test-openbao.yaml` | End-to-end test suite (15 assertions) |

## Testing

The test suite validates seal status, HA election, auth methods, KV secrets,
policies, Raft health, and metrics. Runs as a Kubernetes Job in the `openbao`
namespace.

**File**: `tests/test-openbao.yaml`

**Prerequisite** — create a secret with the root token:

```bash
kubectl create secret generic openbao-test-token \
  -n openbao \
  --from-literal=token=<root-token>
```

**What it tests** (15 assertions):

| Section | Tests |
|---|---|
| 1. All 3 pods unsealed | Each pod reports `sealed: false` |
| 2. Exactly 1 active node | Health endpoint returns 200 on exactly 1 pod (429 = standby) |
| 3. Token auth | Root token self-lookup succeeds |
| 4. Auth methods | `token/` and `kubernetes/` auth enabled |
| 5. KV secrets engine | Enable KV v2, write secret, read back, metadata delete, confirm gone |
| 6. Policy list | `root` and `default` policies present |
| 7. Raft peer list | ≥3 Raft peers reported |
| 8. Metrics endpoint | `/v1/sys/metrics` accessible unauthenticated, returns `vault_core_unsealed` |

**Run**:

```bash
kubectl apply -f tests/test-openbao.yaml
kubectl logs -n openbao job/openbao-test --follow
kubectl delete -f tests/test-openbao.yaml   # cleanup (also auto-deletes after 5 min)
```

> **Note on KV v2 deletion**: The test uses `bao kv metadata delete` (not
> `kv delete` or `kv destroy`) to completely remove the key including all
> version metadata. This is required for the "confirm gone" assertion to pass —
> `kv delete` is a soft-delete and `kv get` still exits 0.

## Common Commands

```bash
# Seal status across all pods
for i in 0 1 2; do
  echo -n "openbao-$i: "
  kubectl exec -n openbao openbao-$i -- bao status 2>/dev/null | grep -E "Sealed|HA Mode"
done

# List secrets engines
kubectl exec -n openbao openbao-0 -- bao secrets list

# List auth methods
kubectl exec -n openbao openbao-0 -- bao auth list

# Write a secret
kubectl exec -n openbao openbao-0 -- bao kv put -mount=secret myapp/config key=value

# Read a secret
kubectl exec -n openbao openbao-0 -- bao kv get -mount=secret myapp/config

# Raft peer list
kubectl exec -n openbao openbao-0 -- bao operator raft list-peers

# Upgrade
helm upgrade openbao openbao/openbao -n openbao -f openbao-values.yaml
# Then delete pods manually (OnDelete strategy):
kubectl delete pod -n openbao openbao-0
# Unseal pod-0 before pod-1/2 will schedule
kubectl exec -it -n openbao openbao-0 -- bao operator unseal
```

## Known Issues / Notes

- Auto-unseal is not configured. Manual unseal required after any pod restart
  or cluster reboot.
- The Kubernetes auth method must be re-configured if the cluster CA or service
  account tokens rotate.
- Metrics use the `vault_` prefix (not `bao_`) — this is intentional for
  Vault-compatible tooling compatibility.

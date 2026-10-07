# OpenBao

## Overview

OpenBao is an open-source fork of HashiCorp Vault, deployed as a 3-node HA
cluster using Raft consensus. It provides secrets management, dynamic
credentials, and Kubernetes auth for workloads running in the cluster.

## Installation

| Component | Details |
|---|---|
| Chart | `openbao/openbao` |
| Image | `quay.io/openbao/openbao:2.7.1` (chart 0.30.2, upgraded 2026-10-05) |
| Namespace | `openbao` |
| Storage | Raft integrated (BoltDB), `local-path` PVC per pod |
| Seal | **static auto-unseal** (Secret `openbao-static-seal`), recovery keys 5/3 |

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

## Auth Methods, policies, roles

| Method | Purpose |
|---|---|
| `token/` | Root token (initial access only — keep off-site, revoke once an admin login exists) |
| `oidc/` | **Owner login via Zitadel** (auth.geekstyle.net → Google); role `admin` (default) → policy `admin`, 8 h tokens |
| `kubernetes/` | Pod identity (`kubernetes_host=https://kubernetes.default.svc`) |

| Policy | Grants | Used by (kubernetes role → ServiceAccount) |
|---|---|---|
| `external-secrets` | read `secret/data/k8s/*`, read/list `secret/metadata/k8s/*` | role `external-secrets` → `external-secrets/external-secrets` (ESO) |
| `test-suite` | read sys/auth, sys/mounts, raft config; list policies; scratch KV under `secret/test/*` | role `test-suite` → `openbao/openbao-test` |
| `admin` | everything incl. `sudo` (not root) | OIDC role `admin`, `bound_claims` email = owner's Gmail |

Secrets engine: **KV v2 at `secret/`**. Convention: app secrets live at `secret/k8s/<namespace>/<name>` and are
synced into Kubernetes by External Secrets Operator (see `../external-secrets/README.md`).

## Unseal — automatic (since 2026-10-05)

**History:** installed 2026-03-21 with Shamir unseal keys (5/3). The pods restarted ~2026-07-22 and stayed sealed
for over two months unnoticed (nothing consumed OpenBao). The original unseal keys were lost, so on 2026-10-05 the
cluster was **wiped and re-initialised** (no data was in use) with **static auto-unseal**, and upgraded to 2.7.1.

- `seal "static"` in `openbao-values.yaml` reads a 32-byte key (64 hex chars, **no trailing newline** — a newline
  makes OpenBao fail with "unknown encoding for AES-256 key") from Secret `openbao/openbao-static-seal` mounted at
  `/openbao/seal/key`. Every pod unseals itself on start; verified by deleting a pod.
- Initialised with `bao operator init -recovery-shares=5 -recovery-threshold=3`. **Recovery keys** are not unseal
  keys: they're needed to generate a new root token (`bao operator generate-root`), rekey, etc.
- **Off-site (owner):** the static seal key, the 5 recovery keys and the initial root token. Without the seal key the
  Raft data cannot be decrypted — a backup of the Secret alone is not enough if etcd is lost.
- Trade-off: anyone who can read the `openbao-static-seal` Secret *and* the data can decrypt it (same trust boundary
  as cluster-admin on this cluster). Upgrade path later: a transit/KMS seal.
- Key rotation: add `previous_key`/`previous_key_id` with the old key, new `current_key`/`current_key_id`, roll pods.

> **Important**: The StatefulSet uses `OnDelete` update strategy — after a `helm upgrade`, delete pods manually.
> `OrderedReady` means pod-1/pod-2 are only created once pod-0 is Ready, and scale-down stalls while pods are
> unhealthy (delete pods directly in that case).

## Admin login (Zitadel SSO) — LAN-free

OpenBao has no LoadBalancer/Ingress (plain-HTTP listener), so admin access is via a tunnel to `localhost`. The
Zitadel app "OpenBao" (project `homelab`, devMode for the http://localhost redirects) allows exactly
`http://localhost:8200/ui/vault/auth/oidc/oidc/callback` (UI) and `http://localhost:8250/oidc/callback` (CLI).

```bash
# With kubectl on your machine:
kubectl -n openbao port-forward svc/openbao-active 8200:8200
# …or via node1 (no local kubectl):
ssh -L 8200:127.0.0.1:8200 ubuntu@<node1> 'kubectl -n openbao port-forward svc/openbao-active 8200:8200'

# UI: http://localhost:8200 → Method "OIDC", role empty/"admin" → Sign in with OIDC Provider
# CLI (bao installed locally, port 8250 free):
export BAO_ADDR=http://localhost:8200
bao login -method=oidc            # opens the browser, token valid 8 h (max 24 h)
```

The OpenBao role is bound to the owner's verified email (`bound_claims`); Zitadel additionally refuses tokens to users
without a `homelab` grant. To add another admin, append their email to `bound_claims.email` (JSON write:
`bao write auth/oidc/role/admin - < role.json`; the CLI can't take a JSON map as `key=value`).

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

**Auth** — no stored token: the Job's ServiceAccount `openbao-test` logs in via the kubernetes auth role
`test-suite` (15-min token, policy `test-suite`). Result 2026-10-05 on 2.7.1: **15/15**.

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
# Pods auto-unseal (static seal); pod-0 must be Ready before pod-1/2 schedule
kubectl exec -it -n openbao openbao-0 -- bao operator unseal
```

## Known Issues / Notes

- Auto-unseal is not configured. Manual unseal required after any pod restart
  or cluster reboot.
- The Kubernetes auth method must be re-configured if the cluster CA or service
  account tokens rotate.
- Metrics use the `vault_` prefix (not `bao_`) — this is intentional for
  Vault-compatible tooling compatibility.

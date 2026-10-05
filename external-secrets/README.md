# External Secrets Operator (ESO)

Syncs secrets from **OpenBao** into ordinary Kubernetes Secrets, so apps keep reading Secrets while the source of
truth lives in OpenBao.

| Detail | Value |
|---|---|
| Chart | `external-secrets/external-secrets` **2.11.0** (ns `external-secrets`), values in `values.yaml` |
| Store | `ClusterSecretStore/openbao` → `http://openbao-active.openbao.svc.cluster.local:8200`, KV v2 `secret/` |
| Auth | OpenBao kubernetes auth, role `external-secrets` (ServiceAccount `external-secrets/external-secrets`) |
| Scope | policy `external-secrets` = **read-only `secret/k8s/*`** — anything else is denied (tested) |

## Install

```bash
helm upgrade --install external-secrets external-secrets/external-secrets \
  -n external-secrets --create-namespace --version 2.11.0 -f values.yaml
kubectl apply -f clustersecretstore-openbao.yaml
kubectl get clustersecretstore openbao        # READY True, "store validated"
```

## Using it

1. Put the secret in OpenBao under `secret/k8s/<namespace>/<name>`:
   `bao kv put -mount=secret k8s/myapp/db password=...`
2. Add an ExternalSecret next to the app:

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata: { name: myapp-db, namespace: myapp }
spec:
  refreshInterval: 1h
  secretStoreRef: { kind: ClusterSecretStore, name: openbao }
  target: { name: myapp-db }          # the Kubernetes Secret ESO creates/owns
  data:
    - secretKey: password
      remoteRef: { key: k8s/myapp/db, property: password }
```

Verified 2026-10-05: value written to OpenBao → synced Secret matched; a path outside `k8s/` → `SecretSyncedError`,
no Secret created.

## Migrating existing secrets (next step, per app)

Candidates currently held only as plain Kubernetes Secrets: Zitadel (`zitadel-db`, `iam-admin-pat`), OIDC clients
(`gitlab/gitlab-oidc`, `monitoring/grafana-oidc`, `ai-services/open-webui-oidc`), `cloudflared/tunnel-token`,
LiteLLM key, Honcho. For each: copy the value into `secret/k8s/<ns>/<name>`, replace the hand-made Secret with an
ExternalSecret of the same name, verify the app, then remove the manual creation step from its README.
**Not** the OpenBao static seal key (it must exist before OpenBao can start).

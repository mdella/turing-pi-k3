# Zitadel — central identity provider (https://auth.geekstyle.net)

One login for the homelab. Apps (GitLab, Hermes dashboard, Grafana, …) trust Zitadel over
OIDC; Zitadel in turn federates to social identity providers (Google first; Facebook,
GitHub… can be added later without touching any app).

| Detail | Value |
|---|---|
| Chart | `zitadel/zitadel` 10.0.6 → Zitadel **v4.15.3** + login UI v2 |
| Namespace | `zitadel` |
| Database | own Postgres 17 StatefulSet `zitadel-db` (Longhorn 10 Gi), DSN in Secret `zitadel-db` |
| Masterkey | Secret `zitadel-masterkey` (32 chars) — **also needed to restore a backup**; keep an offline copy |
| Backups | CronJob `zitadel-db-backup` 01:45 UTC → PVC `zitadel-backups`, 14 days |
| Exposure | Cloudflare Tunnel, **not** ingress-nginx (Zitadel needs end-to-end HTTP/2) |
| Org | `GeekStyle` (first instance) |
| Automation user | machine user `iam-admin` (IAM_OWNER), PAT in Secret `iam-admin-pat` (expires 2029-01-01) |

## Install

```bash
kubectl apply -f zitadel-db.yaml        # after creating Secret zitadel-db (see file header)
kubectl -n zitadel create secret generic zitadel-masterkey \
  --from-literal=masterkey="$(tr -dc A-Za-z0-9 </dev/urandom | head -c 32)"
kubectl apply -f backup.yaml
helm upgrade --install zitadel zitadel/zitadel -n zitadel --version 10.0.6 -f zitadel-values.yaml
```

`initJob.command: zitadel` — the database and owner already exist, so only ZITADEL's own
schemas are created (the full init needs a Postgres superuser). With the init job disabled
entirely, setup fails with `relation "eventstore.events2" does not exist`.

## Tunnel routing (Cloudflare, tunnel `k3s-geekstyle`)

Order matters — the path rule must come before the host-wide rule:

| Hostname | Path | Origin |
|---|---|---|
| `auth.geekstyle.net` | `^/ui/v2/login` | `http://zitadel-login.zitadel.svc.cluster.local:3000` |
| `auth.geekstyle.net` | (all) | `http://zitadel.zitadel.svc.cluster.local:8080`, `originRequest.http2Origin: true` |

## Authorization model

Project **`homelab`** holds every homelab app, with roles `admin` and `dev`. Project settings
*Assert roles on authentication*, *Check authorization on authentication* and *Check for
project on authentication* are on, so **Zitadel refuses to issue a token for a homelab app to
anyone without a role grant**. Signing in with any Google account therefore gets a stranger
nothing. (Hermes' dashboard OIDC has no allowlist of its own — this is what protects it.)

To give someone access: Zitadel console → Projects → homelab → Authorizations → add the user
with a role.

Second project **`luna`** (2026-10-07, role `user`, same checks) for the Luna chat front end only — granting someone
`luna` gives them nothing in `homelab`. See `../luna/README.md`.

## API access (automation)

```bash
PAT=$(kubectl -n zitadel get secret iam-admin-pat -o jsonpath='{.data.pat}' | base64 -d)
curl -s -H "Authorization: Bearer $PAT" https://auth.geekstyle.net/auth/v1/users/me
```

## Restore

Scale Zitadel down, `pg_restore --clean -d zitadel <dump>` into `zitadel-db`, make sure the
**same masterkey** is in `zitadel-masterkey`, scale up.

# Zitadel — central identity provider (https://auth.geekstyle.net)

One login for the homelab. Apps (GitLab, Hermes dashboard, Grafana, …) trust Zitadel over
OIDC; Zitadel in turn federates to social identity providers (Google first; Facebook,
GitHub… can be added later without touching any app).

| Detail | Value |
|---|---|
| Chart | `zitadel/zitadel` 10.4.0, images pinned to Zitadel **v4.20.6** + login UI v2 (see Upgrades) |
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
helm upgrade --install zitadel zitadel/zitadel -n zitadel --version 10.4.0 -f zitadel-values.yaml
```

`initJob.command: zitadel` — the database and owner already exist, so only ZITADEL's own
schemas are created (the full init needs a Postgres superuser). With the init job disabled
entirely, setup fails with `relation "eventstore.events2" does not exist`.

## Upgrades

The chart lags the app (10.4.0 and 10.5.0 both ship v4.19.2), so `image.tag` and `login.image.tag` in
`zitadel-values.yaml` are pinned by tag and digest, with the previous digest in a comment. An upgrade is: manual
backup (`kubectl -n zitadel create job --from=cronjob/zitadel-db-backup zitadel-db-backup-pre-<ver>`), compare
`helm -n zitadel get values zitadel` with the file, then the install command above with `--wait`. The setup job
runs the migrations as a pre-upgrade hook.

### v4.20.0 → v4.20.6 (2026-11-26)

Security fixes in 4.20.3 and 4.20.5 (login: OIDC/SAML only completed with a valid session, external IdP sign-in
bound to the browser that started it, Login V1 codes bound to the user, second factor required before adding an
authenticator). Upgrade notes of 4.20.3 checked against this setup:

- custom login UIs now need `IAM_LOGIN_CLIENT`: we use the chart's hosted Login V2 with its own login client, so
  not affected
- password checks follow the org's login policy: sign-in is Google, not affected
- sign-ins in progress during the upgrade had to be restarted

Backup `zitadel-2026-11-26T182907Z.dump` taken first. Upgrade took 1.5 min (setup job about 1 min). Checked after:
`/debug/healthz` 200, the discovery document, the Login V2 page, the `iam-admin` PAT on the management API, and an
OIDC authorize request for the console reaching `/ui/v2/login/loginname` with Google offered. A full Google sign-in
was left to the owner.

Seen after the upgrade, harmless so far: the login UI sends `x-zitadel-public-host` twice (the chart's
`CUSTOM_REQUEST_HEADERS` plus its own), Zitadel logs `invalid host in header, ignoring header`, and one call
(security settings) gets a 400. Not known whether this also happened on v4.20.0. Rollback: put the v4.20.0 digests
back and rerun the install command (no schema rollback needed for a patch release; restore the dump if it is).

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

Third project **`scm`** (2026-10-08, role `user`, same checks) holds only the **GitLab** app. GitLab moved out of
`homelab` so a GitLab user (e.g. a family member) isn't also issued tokens for the Hermes dashboard / Grafana — Hermes'
dashboard OIDC has no allowlist and relies purely on the `homelab` project gate. The old GitLab app in `homelab` is
deactivated. To give someone GitLab: grant them `scm` → `user` (and pre-create/link their GitLab user, see
`../gitlab/README.md`).

## API access (automation)

```bash
PAT=$(kubectl -n zitadel get secret iam-admin-pat -o jsonpath='{.data.pat}' | base64 -d)
curl -s -H "Authorization: Bearer $PAT" https://auth.geekstyle.net/auth/v1/users/me
```

## Restore

Scale Zitadel down, `pg_restore --clean -d zitadel <dump>` into `zitadel-db`, make sure the
**same masterkey** is in `zitadel-masterkey`, scale up.

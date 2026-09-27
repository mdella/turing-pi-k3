# Ghost Blog

## Overview

Ghost 5.x blog deployed on k3s, served at `http://blog.geekstyle.net` via
ingress-nginx. Uses a dedicated standalone MariaDB (not the Galera cluster).
Content volume is on Longhorn for HA storage.

## Credentials Setup

Two files contain `CHANGE_ME` placeholders:

| File | Field | Notes |
|---|---|---|
| `ghost-db-backup-cronjob.yaml` | `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | SeaweedFS S3 credentials — must match `../seaweedfs/s3-config.yaml` |
| `ghost-db-backup-cronjob.yaml` | `DB_PASS` | Ghost MariaDB `ghost` user password — find in the `ghost` namespace deployment env vars |
| `tests/test-ghost.yaml` | `CONTENT_KEY` | Ghost Content API key — generate in Ghost Admin → **Integrations** → **Add custom integration** |

## Stack

| Component | Details |
|---|---|
| Ghost image | `ghost:6.30.0-alpine` |
| Database | Standalone MariaDB 10.11 (StatefulSet in `ghost` namespace) |
| Content storage | Longhorn RWO PVC, 5Gi (`ghost-content`) |
| DB storage | Longhorn RWO PVC, 1Gi (`mariadb-data-mariadb-0`) |
| Ingress | `blog.geekstyle.net` → ingress-nginx → ClusterIP :80 |
| External IP | `192.168.4.204` (MetalLB LoadBalancer) |
| URL (env) | `https://blog.geekstyle.net` (set 2026-09-27) |

## Services

| Service | Type | Address | Purpose |
|---|---|---|---|
| `ghost` | LoadBalancer | `192.168.4.204:80` | External HTTP access |
| `mariadb` | ClusterIP | `mariadb.ghost.svc.cluster.local:3306` | Ghost DB |

## Configuration

Ghost is configured via environment variables in the Deployment:

| Variable | Value |
|---|---|
| `url` | `https://blog.geekstyle.net` |
| `database__client` | `mysql` |
| `database__connection__host` | `mariadb.ghost.svc.cluster.local` |
| `database__connection__database` | `ghost` |

> Fixed 2026-09-27: `url` is `https://blog.geekstyle.net` (was the LoadBalancer IP).
> Post URLs, email links, and canonical tags will reference the IP. Fix by updating
> the deployment env var and running `kubectl rollout restart deployment/ghost -n ghost`.

## Security Headers

Security headers are added at the ingress-nginx layer via global `add-headers`
ConfigMap (`ingress-nginx/ingress-nginx-custom-response-headers`):

| Header | Value |
|---|---|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `SAMEORIGIN` |
| `X-XSS-Protection` | `1; mode=block` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |

The `global-allowed-response-headers` key in the ingress-nginx ConfigMap must
list these headers for `more_set_headers` to apply them.

## Backups

Ghost MariaDB is backed up daily at **02:00 UTC** by the `ghost-db-backup` CronJob in the `ghost` namespace.

| Detail | Value |
|---|---|
| Destination | SeaweedFS S3 `ghost-backups` bucket |
| Format | `ghost-YYYY-MM-DDTHHMMSSZ.sql.gz` (gzipped mysqldump) |
| Retention | 30 days |
| Manifest | `ghost-db-backup-cronjob.yaml` |

```bash
# Trigger a manual backup
kubectl create job ghost-db-backup-manual --from=cronjob/ghost-db-backup -n ghost

# Check backup job logs
kubectl logs -n ghost -l job-name=ghost-db-backup-manual

# List backups in SeaweedFS
kubectl run s3ls --image=amazon/aws-cli --restart=Never -n seaweedfs \
  --env AWS_ACCESS_KEY_ID=<YOUR_S3_ACCESS_KEY> \
  --env AWS_SECRET_ACCESS_KEY=<YOUR_S3_SECRET_KEY> \
  --env AWS_DEFAULT_REGION=us-east-1 \
  -- --endpoint-url http://seaweedfs-s3.seaweedfs.svc.cluster.local:8333 s3 ls s3://ghost-backups/
```

## Email

Email transport is set to `Direct` (Ghost sends directly to recipient MX).
This is unreliable for production — subscriber emails and staff notifications
may be rejected as spam. SMTP should be configured for any real usage.

## TLS / public access (2026-09-27)

Public via the **Cloudflare Tunnel** (see `../cloudflare/README.md`) — no NAT/port-forward, no cert-manager:
TLS terminates at Cloudflare; tunnel → ingress-nginx → `ghost` Service. ingress-nginx runs with
`use-forwarded-headers: true`, so Ghost sees `X-Forwarded-Proto: https` (no redirect loop) and the global
security headers still apply.

- `kubectl set env deployment/ghost -n ghost url=https://blog.geekstyle.net`
- **Admin** `/ghost` is behind **Cloudflare Access** (Zitadel login, owner only); `/ghost/api/content` has an Access
  *bypass* app so the public theme/search/portal keep working. Members API (`/members/…`) is public as usual.
- LAN: `http://192.168.4.204` (LoadBalancer) still reaches the pod directly.
- **No email is configured** (no `mail__*` env). Ghost 6's staff device verification (emailed login codes) therefore
  locked staff out → disabled with `security__staffDeviceVerification=false` (2026-09-27); the second factor is
  Cloudflare Access (Zitadel → Google 2FA) in front of `/ghost`. Configure SMTP (Mailgun recommended) before using
  newsletters/member sign-up or password resets, then consider turning verification back on.
- ActivityPub ("Network"/social web) isn't set up for self-hosting — startup logs `Could not get webhook secret for
  ActivityPub`; harmless.

## Files

| File | Purpose |
|---|---|
| `ghost-ingress.yaml` | Ingress for `blog.geekstyle.net` (TLS at Cloudflare; no tls block needed) |
| `ghost-security-headers.yaml` | Security headers ConfigMap (ghost namespace) |
| `ghost-db-backup-cronjob.yaml` | MariaDB backup CronJob — daily at 02:00 UTC → SeaweedFS S3 |
| `tests/test-ghost.yaml` | End-to-end test suite (29 assertions) |

## Testing

**File**: `tests/test-ghost.yaml`

**What it tests** (29 assertions):

| Section | Tests |
|---|---|
| 1. Core HTTP | Homepage, admin UI, RSS, sitemap, sitemap-posts all return 200 |
| 2. Admin API | `/ghost/api/admin/site/` returns version and URL |
| 3. Content API | Posts, authors, tags, settings return 200; invalid key returns 401 |
| 4. Security headers | X-Content-Type-Options, X-Frame-Options, Referrer-Policy via ingress |
| 5. Response times | Homepage <2s, admin API <500ms, RSS <2s |
| 6. Ghost-specific | Member JS served, RSS valid XML, sitemap valid |
| 7. Error handling | Non-existent page → 404, missing post API → 404 |
| 8. DB consistency | Content API and settings backed by live database |

```bash
kubectl delete job ghost-test -n ghost 2>/dev/null
kubectl apply -f tests/test-ghost.yaml
kubectl logs -n ghost job/ghost-test --follow
kubectl delete -f tests/test-ghost.yaml
```

**Baseline results** (2026-04-21, Ghost 6.30.0): 29/29 passed
- Homepage: ~100ms, Admin API: ~12ms, RSS: ~53ms (all internal cluster)

## Common Commands

```bash
# Pod status
kubectl get pods -n ghost -o wide

# Ghost logs
kubectl logs -n ghost -l app=ghost --tail=50

# Restart Ghost (e.g. after config change)
kubectl rollout restart deployment/ghost -n ghost

# Ghost version
kubectl exec -n ghost deploy/ghost -- ghost --version

# Connect to Ghost DB
kubectl exec -it -n ghost statefulset/mariadb -- \
  mariadb -ughost -p<YOUR_GHOST_DB_PASSWORD> ghost

# Check content volume
kubectl get pvc -n ghost
```

## Known Issues / Notes

- Ghost image is pinned to `ghost:6.30.0-alpine`. Upgrade by pinning to a newer
  Ghost 6.x tag and checking for migration errors in pod logs on first boot.
- MariaDB is backed up daily at 02:00 UTC by `ghost-db-backup` CronJob.
  Backups land in SeaweedFS `ghost-backups` bucket as gzipped SQL, retained 30 days.
  Manual dumps: `~/ghost-db-backup-20260403.sql` (pre-upgrade), `~/ghost-db-backup-pre-v6-20260421.sql` (pre-v6).
- ~~`url` pointed to the LB IP~~ — fixed 2026-09-27 (`https://blog.geekstyle.net`).

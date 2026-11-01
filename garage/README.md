# Garage (S3 on the NAS)

[Garage](https://garagehq.deuxfleurs.fr/) is a small S3-compatible object store. It runs as a single Docker
container on the UGREEN NAS, outside the k3s cluster, so large objects (first: GitLab LFS) live on the NAS
instead of on Longhorn.

_Added 2026-11-01._

## Where it runs

| | |
|---|---|
| Host | UGREEN DXP6800 Ultra, UGOS Pro 1.20.0.0142, `nas.geekstyle.net` = `192.168.4.20` (VLAN 14, Kea reservation on OPNsense) |
| Image | `dxflrs/garage:v2.5.0`, deployed as a UGOS **Docker → Project** (compose) |
| S3 API | `http://nas.geekstyle.net:3900`, region `garage`, **path-style** only |
| Admin API | `http://nas.geekstyle.net:3903` (bearer token), also `/metrics` (metrics token) and `/health` |
| Not published | 3901 (RPC, single node) and 3902 (static web) |
| Storage | Volume 1 (~2.17 TB) via shared folder `docker`: `/volume1/docker/garage/{garage.toml,meta,data}` |

The NAS and the cluster nodes share VLAN 14 at 10G, so cluster → Garage traffic doesn't cross OPNsense. There is no
TLS; keep it LAN-only (nothing forwards to it from outside).

## Files

- [`docker-compose.yml`](docker-compose.yml): paste into UGOS Docker → Project → Create.
- [`garage.toml.example`](garage.toml.example): the config with `CHANGE_ME` in place of the three secrets. The real
  `garage.toml` lives only on the NAS (and in the operator's local config); never commit it.

Config choices: `replication_factor = 1` (one node; the NAS RAID is the redundancy), `db_engine = "sqlite"`,
metadata snapshots every 6 h.

## Setting up the NAS (UGOS Pro)

1. **App Center → Docker → Install**, location **Volume 1**.
2. **Files → Shared Folder → Create** `docker` on Volume 1 (Docker may already have created it). Inside it, make
   ordinary folders `garage/meta` and `garage/data`. Only `docker` is a shared folder; Garage's folders must never be
   exported over SMB/NFS (writing into them corrupts the store).
3. Upload `garage.toml` (secrets filled in) to `docker/garage/`.
4. **Docker → Project → Create**, name `garage`, paste the compose file, deploy.

NFS (for backups etc.) is configured in the **web UI only** (Control Panel → File Service → NFS); the iPad app
doesn't show it.

## First-time cluster setup (admin API)

Garage stores nothing until the node has a role in the layout. With `T` = the admin token:

```bash
U=http://nas.geekstyle.net:3903/v2; H="Authorization: Bearer $T"
curl -s -H "$H" $U/GetClusterStatus                     # node id, disk sizes
curl -s -H "$H" -X POST $U/UpdateClusterLayout -H 'Content-Type: application/json' \
  -d '{"roles":[{"id":"<node id>","zone":"geekstyle","capacity":2000000000000,"tags":["nas"]}]}'
curl -s -H "$H" -X POST $U/ApplyClusterLayout -H 'Content-Type: application/json' -d '{"version":1}'
curl -s http://nas.geekstyle.net:3903/health             # "Garage is fully operational"
```

Done 2026-11-01: layout version 1, zone `geekstyle`, capacity 2 TB (1.8 TiB usable).

## Buckets and keys

```bash
curl -s -H "$H" -X POST $U/CreateBucket -H 'Content-Type: application/json' -d '{"globalAlias":"<bucket>"}'
curl -s -H "$H" -X POST $U/CreateKey    -H 'Content-Type: application/json' -d '{"name":"<key name>"}'   # returns the secret ONCE
curl -s -H "$H" -X POST $U/AllowBucketKey -H 'Content-Type: application/json' \
  -d '{"bucketId":"<id>","accessKeyId":"<GK…>","permissions":{"read":true,"write":true,"owner":false}}'
```

| Bucket | Key | Permissions | Used by |
|---|---|---|---|
| `gitlab-lfs` | `gitlab` | read + write (not owner) | GitLab LFS (not switched over yet) |
| `gitlab-backups` | `gitlab-backup` | read + write (not owner) | `gitlab-backup create` uploads (not switched over yet) |

Each key sees only its own bucket (checked: the backup key is denied on `gitlab-lfs`). Key secrets live in OpenBao at
`secret/k8s/gitlab/garage-s3` (fields `endpoint`, `region`, `lfs_*`, `backup_*`), for External Secrets to sync into
namespace `gitlab`; never in this repo.

Test with the AWS CLI (the endpoint goes in an env var):

```bash
export AWS_ENDPOINT_URL=http://nas.geekstyle.net:3900 AWS_DEFAULT_REGION=garage
export AWS_ACCESS_KEY_ID=… AWS_SECRET_ACCESS_KEY=…
aws s3 cp ./file s3://gitlab-lfs/_smoketest/file && aws s3 ls s3://gitlab-lfs/_smoketest/
```

A 5 MB put / list / get / byte-compare / delete passed on 2026-11-01.

## GitLab LFS on Garage (live since 2026-11-01)

GitLab stays in k3s; only its LFS objects live in Garage.

1. Credentials: [`../gitlab/garage-s3-externalsecret.yaml`](../gitlab/garage-s3-externalsecret.yaml) syncs OpenBao
   `secret/k8s/gitlab/garage-s3` into Secret `gitlab/garage-s3` (all 8 fields; values checked against the Garage keys by hash).
2. [`../gitlab/gitlab.yaml`](../gitlab/gitlab.yaml): consolidated object storage, LFS → bucket `gitlab-lfs`, every other
   object type `enabled = false` (still on the PVC), `proxy_download = true`, `path_style`; the four `GARAGE_*` env vars
   come from the Secret. `hostAliases` pins `nas.geekstyle.net` → 192.168.4.20 because CoreDNS forwards to public
   resolvers, which don't know the Unbound-only name.
3. Applied 20:57Z (pod Ready 21:00Z), then `gitlab-rake gitlab:lfs:migrate`: 6/6 objects (4.16 MB) moved, `lfs_objects`
   = 6 total / 0 filesystem / 6 object storage, no LFS files left on the PVC, every object read back from Garage with
   SHA-256 = oid. Pre-change copies on k3-node1 `~/gitlab-backups/` (`lfs-objects-before-garage-20261101.tgz`,
   `deploy-gitlab-before-garage-20261101.yaml`).

Rollback: re-apply the old Deployment, then the files from the tarball back into `shared/lfs-objects` and
`UPDATE lfs_objects SET file_store = 1` (only for objects that exist locally).

## GitLab backups on Garage (live since 2026-11-01)

`gitlab-backup create` uploads each archive to bucket `gitlab-backups` with the `gitlab-backup` key
(`backup_upload_connection`, storage-specific form; `GARAGE_BACKUP_*` env from Secret `garage-s3`). Applied 21:15Z.
Test `BACKUP=garage-test-20261101`: 4,912,332,800 bytes (registry 4.6 GB, artifacts 278 MB, pages 10 MB, DB, repos),
upload 21:26:59 → 21:29:38Z (~31 MB/s), object size in Garage matches. The older upgrade archives
`pre-19.3-20260927` and `pre-19.4-20261009` were copied into the bucket first (SHA-256 verified).

- `backup_keep_time` (7 days) prunes only **local** archives with GitLab's default timestamped names; custom
  `BACKUP=` names are never pruned. Nothing prunes the bucket yet.
- LFS objects are not in the archive (they already live in `gitlab-lfs`). `gitlab-secrets.json` and `gitlab.rb` are
  never in it; keep them separately or a restore is impossible.
- No schedule yet: backups only run when started by hand.

### Next (not done)

1. Nightly schedule, retention (local keep_time vs. the 49 Gi PVC; bucket lifecycle), and whether to `SKIP=registry`.
2. Optional later: artifacts, uploads and packages to their own buckets; repositories to a Gitaly container on the
   NAS (never to an NFS share: GitLab doesn't support Git data on NFS). Gitaly's version must match GitLab's exactly.

The NAS becomes a single point of failure for whatever moves there; back it up somewhere else.

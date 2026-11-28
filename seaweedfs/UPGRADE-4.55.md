# SeaweedFS upgrade: 4.47 → 4.55 (completed 2026-11-28)

Done 2026-11-27 23:55 → 2026-11-28 00:20 UTC, following the staged procedure in [UPGRADE-4.47.md](UPGRADE-4.47.md):
masters, then volume servers, then filers, `--reset-then-reuse-values`, image overrides cleared at the end.
Release `seaweedfs` rev 11 = chart 4.55.0, all 10 pods `chrislusf/seaweedfs:4.55` (arm64).

## Why
4.47 was affected by a large batch of advisories published 2026-11-09, several critical. Among them:
unauthenticated admin access to the S3 gateway's internal gRPC services, SSRF and crash through the volume
server, the `weed admin` HTTP server's write operations unauthenticated by default, and bucket-policy bypasses.
Some advisories list no fixed version yet; 4.55 was the latest release.

## What changed (chart 4.47.0 → 4.55.0, rendered with the live values)
- Images 4.47 → 4.55.
- Filer: `WEED_MYSQL_USERNAME/PASSWORD` are now rendered once, from our values, instead of twice (a
  `secretKeyRef` to `seaweedfs-db-secret` plus our plain values).
- Masters get a `checksum/master-config` annotation (roll when their config changes); filer Service gets
  `publishNotReadyAddresses`; the chart's db Secret gets a hook delete policy.
- Release notes 4.48–4.55: S3 now needs dedicated permissions for object-lock headers, lifecycle (Admin), CORS and
  versioning. Our identities don't use those.

## ⚠ Gotcha hit in step 1: the filer lost its database credentials
Because the 4.47 manifest listed `WEED_MYSQL_USERNAME` and `WEED_MYSQL_PASSWORD` **twice**, Helm's patch of the
filer StatefulSet removed both entries (strategic merge on an env list with duplicate names). The new manifest had
them; the live object didn't. filer-2 restarted without them and crash-looped (`Access denied for user ''`).
filer-0 and filer-1 were still the old pods, so S3 kept working.
**Fix:** run the same `helm upgrade` again. Helm's three-way merge sees the live object is missing them and adds
them back. **Check after any filer change:**
`kubectl -n seaweedfs get sts seaweedfs-filer -o json | grep -c 'WEED_MYSQL_USERNAME\|WEED_MYSQL_PASSWORD'` → 2.

## Backups (node1 `~/backups/seaweedfs-upgrade-20261128/`, 0700, not in git)
- Filer metadata: `seaweedfs` DB from Galera, `--hex-blob --skip-extended-insert`, 889 `filemeta` rows.
- Master raft dirs: `tar` of `/data` from inside each master pod (SSH from node1 to the nodes is refused now,
  see below).
- Live Helm values (rev 7).

## Results
- Raft: leader moved master-0 → master-1 during the rollout, 2 peers each, MaxVolumeId 126 throughout.
- 36 volumes × 2 copies at every stage; no `volume.fix.replication` needed.
- No errors in master, volume or filer logs, apart from the known STS signing-key message on filer start.
- S3 anonymous 403 (LAN and https://s3.geekstyle.net); Ghost backup job uploaded through S3 (`admin` identity).
- `tests/test-cluster.yaml` 15/15, after fixing its leader check: it looked for `IsLeader` on master-0, which only
  appears on the current leader.

## Open
- SSH from node1 (`ubuntu`, `id_ed25519`) to k3-node1–4 is refused (publickey). It worked for the 4.47 upgrade.

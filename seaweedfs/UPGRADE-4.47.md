# SeaweedFS upgrade plan: 4.21 → 4.47

Status: **step 0 done 2026-09-25 02:40 UTC; step 1 done 2026-09-25 ~05:45 UTC** (release rev 4: chart 4.47.0,
masters on 4.47, volume + filer held on 4.21). Steps 2–3 pending. (Written 2026-09-24.)

> **Use `--reset-then-reuse-values`, not `--reuse-values`** (Helm ≥ 3.14; node1 has 3.20). With
> `--reuse-values` Helm reuses the old release's values *without* the new chart's defaults, so keys
> added after 4.21 are missing and the render fails:
> `networkpolicy.yaml: nil pointer evaluating interface {}.enabled` (hit on the first step 1 attempt;
> nothing was changed). Cluster state at planning time: release
`seaweedfs` rev 3, chart 4.21.0 / image `chrislusf/seaweedfs:4.21`; 3/3 masters (raft 3 members),
3/3 filers, 3 volume servers, 24 volumes × 2 copies, filer metadata in Galera (`seaweedfs` DB) via ProxySQL.

## What changes (checked, not assumed)
- **Chart diff with the deployed values** (`helm template` of 4.21.0 vs 4.47.0 with `helm get values`):
  the only workload change is the image tag `4.21 → 4.47` on master, filer and volume. Flags, env,
  probes, volumes, node selectors and update strategy are identical; no objects added or removed.
  The one other change: the filer's `WEED_MYSQL_USERNAME/PASSWORD` refs to `seaweedfs-db-secret` become
  `optional: true`. The secret exists (keys `user`, `password`), so no effect.
- **Image** `chrislusf/seaweedfs:4.47` is published for arm64 (RK1 nodes).
- **Release notes 4.22–4.47**, the items that touch this setup:

| Version | Change | Impact here |
|---|---|---|
| 4.23, 4.41, 4.47 | raft library → v1.1.8, v1.2.0 (snapshot race), v1.2.1 (clean shutdown) | Masters' raft state format could change: back up master dirs first (step 0) |
| 4.42 | Heartbeat protocol rework (volume digest, incremental heartbeats) | Mixed master/volume versions during a rollout. Stage it: masters first, then volume servers |
| 4.44 | Leader admits a master that starts with no raft state | Makes master recovery easier |
| 4.45 | Never re-seed raft over committed state under `-raftBootstrap` | Safer |
| 4.45 | S3 denies anonymous access if the identity config loads no identities | Config loads 1 identity (`admin`), no anonymous identity: no change (anonymous already gets 403) |
| 4.34 | Crash-safe vacuum commit (`.cpc` marker) | On-disk change during vacuum; one-way. Rollback of volume servers after a vacuum is untested |
| 4.30 | NFS gateway / inode index removed; `/healthz` probes added | Not used; chart probes unchanged |
| 4.38, 4.46 | MySQL filer store: default CREATE TABLE, pool defaults | Table already exists; no action |

Not in scope: the CSI driver (`chrislusf/seaweedfs-csi-driver:v1.4.12`, separate release in `default`);
Jellyfin (its consumer) isn't running. Check CSI compatibility separately before bringing Jellyfin back.

## Window
Nodes run UTC. Avoid **01:30–03:45 UTC**: `honcho-db-backup` 01:30, `ghost-db-backup` +
`openclaw-daily-snapshot` 02:00, `ghost-daily-snapshot` 03:00, `signal-cli-backup-offnode` 03:25. The
Ghost backup writes to SeaweedFS S3. Expected duration ~45 min, with ~1 min write blips per stage.

## Step 0: preflight and backups (no changes to SeaweedFS)
Run on k3-node1 from `/tmp` (a `~/seaweedfs` folder makes helm ignore `--repo`).
```bash
cd /tmp; K="sudo k3s kubectl"; H="sudo helm --kubeconfig /etc/rancher/k3s/k3s.yaml"; B=/var/backups/seaweedfs-upgrade-$(date +%Y%m%d)
sudo mkdir -p $B
# 1. Filer metadata (the Galera `seaweedfs` DB). Everything that maps paths to file chunks.
$K -n mariadb exec mariadb-galera-0 -c mariadb -- sh -c 'mariadb-dump -uroot -p"$MARIADB_ROOT_PASSWORD" --single-transaction seaweedfs' \
  | gzip | sudo tee $B/seaweedfs-filer-meta.sql.gz >/dev/null
# 2. Master raft/metadata dirs (hostPath) on each master node
for n in k3-node1 k3-node3 k3-node4; do ssh $n "sudo tar -czf - -C /data/seaweedfs master" | sudo tee $B/master-$n.tgz >/dev/null; done
# 3. Record the rollback point and a baseline
$H history seaweedfs -n seaweedfs | tail -2          # expect rev 3 = 4.21.0
$H get values seaweedfs -n seaweedfs -o yaml | sudo tee $B/values-rev3.yaml >/dev/null
# 4. Pre-pull the image so restarts are quick
for n in k3-node1 k3-node3 k3-node4; do ssh $n "sudo k3s crictl pull docker.io/chrislusf/seaweedfs:4.47"; done
```
**Baseline checks** (repeat after every stage):
- raft: `curl http://<master pod IP>:9333/cluster/status` shows a leader + 2 peers
- volumes: `/vol/status` gives 24 volumes, all 2 copies
- filers: 3/3 Ready; `GET http://<filer IP>:8888/buckets/` lists `ghost-backups` etc.
- S3: `curl -o /dev/null -w %{http_code} http://192.168.4.208:8333/` returns `403`
- one real S3 round-trip: `kubectl -n ghost create job --from=cronjob/ghost-db-backup sw-upgrade-check-N`
  and confirm it uploads (it also rotates backups older than 30 days; that's fine now)

## Step 1: masters only
Chart 4.47.0, but hold volume servers and filers on the 4.21 image. Filers restart once here anyway
(their template gets the `optional: true` change), still on 4.21.
```bash
$H upgrade seaweedfs seaweedfs --repo https://seaweedfs.github.io/seaweedfs/helm --version 4.47.0 -n seaweedfs \
  --reset-then-reuse-values --set volume.imageOverride=chrislusf/seaweedfs:4.21 --set filer.imageOverride=chrislusf/seaweedfs:4.21
$K -n seaweedfs rollout status sts/seaweedfs-master --timeout=10m
```
Masters roll one at a time (2 of 3 always up, so raft keeps a majority). Check that raft has 3 members
and the same leader-election behaviour, `MaxVolumeId` unchanged (96), and volume servers re-registered
(24 volumes × 2). **Stop here and roll back if raft doesn't reform.**

**Result (2026-09-25):** masters rolled master-2 → master-1 → master-0 (~4 min, 2 of 3 always up).
All three agree: leader master-0, 2 peers, MaxVolumeId 96; `weed version` = 4.47 arm64; 4.21 volume
servers re-registered all 24 volumes × 2 copies (mixed heartbeat versions OK); filers didn't restart
(template identical); 3 buckets listed; S3 anonymous 403; 0 master errors.

## Step 2: volume servers
```bash
$H upgrade seaweedfs seaweedfs --repo https://seaweedfs.github.io/seaweedfs/helm --version 4.47.0 -n seaweedfs \
  --reset-then-reuse-values --set volume.imageOverride=null --set filer.imageOverride=chrislusf/seaweedfs:4.21
$K -n seaweedfs rollout status sts/seaweedfs-volume --timeout=15m
```
One server at a time. While one is down, volumes with a copy on it can't take writes; S3 writes go to
the other volumes. Check all 24 volumes × 2 copies again afterwards, then run
`volume.fix.replication` (dry run, then `-apply`) if any volume came back single-copy.

## Step 3: filers (and S3)
```bash
$H upgrade seaweedfs seaweedfs --repo https://seaweedfs.github.io/seaweedfs/helm --version 4.47.0 -n seaweedfs \
  --reset-then-reuse-values --set filer.imageOverride=null
$K -n seaweedfs rollout status sts/seaweedfs-filer --timeout=10m
```
Then the full baseline, including the S3 round-trip job. Finally clear the overrides from the stored
values so later upgrades don't inherit them: `$H get values seaweedfs -n seaweedfs | grep -i imageOverride`
should show nothing (both were reset above). Update `seaweedfs-values.yaml` / README to 4.47.

## Rollback
- **After step 1 or 2:** `$H rollback seaweedfs 3 -n seaweedfs` (rev 3 = chart 4.21.0, image 4.21).
  If masters don't reform raft on 4.21 (raft library downgrade), stop all masters, restore
  `/data/seaweedfs/master` on each node from `master-<node>.tgz`, and start them again.
- **Filer metadata:** it lives in Galera and the filer schema doesn't change between these versions;
  `seaweedfs-filer-meta.sql.gz` is the safety net.
- **Volume data** isn't rewritten by the upgrade itself. Vacuum after 4.34 writes a new marker file;
  downgrading volume servers after a vacuum has run is untested, so don't wait days before deciding.

## Known unknowns
- No upstream statement on mixed-version master/volume compatibility across 4.42's heartbeat change.
  Staging (step 1 → 2) keeps the mixed period short and ordered.
- Raft downgrade from v1.2.x state to 4.21's v1.1.x is untested; hence the master dir backups.
- CSI driver v1.4.12 against a 4.47 filer: untested (not needed until Jellyfin runs again).

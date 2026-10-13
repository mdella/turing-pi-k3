# Clean full-cluster power-down / power-up

Written for the move to a new UPS (planned 2026-10-12, moved to the afternoon of 2026-10-13 PDT) and the Arista switch, which removes the wireless eero hop between the
Turing Pi and OPNsense. Reusable for any planned full outage. Run everything on **k3-node1**.

| Step | Script | Time | What it does |
|---|---|---|---|
| 1 | `move-prep.sh` | ~25–40 min | Checks: nodes Ready, Longhorn healthy, Galera size 3, Hermes delivery ledger has no undelivered messages (otherwise aborts; `FORCE=1` skips). Then the backups listed below, suspends all CronJobs, scales every non-operator Deployment/StatefulSet with a Longhorn PVC to 0 (20 workloads when checked on 2026-10-12), waits until **all Longhorn volumes are detached**, and cordons all nodes. |
| 2 | `move-shutdown.sh` | ~10 min | Asks you to type `poweroff`, then powers off node4 → node3 → node2 (one-shot privileged pod per node), waiting for each to go silent. Powers off node1 last, which ends any Claude session running there. |
| — | (physical) | | Turn the slots off in the BMC, unplug, move, plug into the Arista/UPS. **BMC firmware upgrade goes here**, see below. |
| 3 | `move-restore.sh` | ~45–60 min | Waits for 4 Ready nodes; pings OPNsense and node2 (wired should be <1 ms, the wireless hop was 5–6 ms); uncordons; waits for longhorn-manager and the Galera operator's recovery; scales StatefulSets back up, then Deployments (GitLab gets 25 min); resumes the CronJobs; smoke checks. |

State lives in `~/cluster-move/<date>/` on node1 (mode 700, **not in git**): `workloads.json`, `cronjobs.txt`, and
the backups.

**Backups taken by `move-prep.sh`:**
- etcd snapshot `pre-move-*`, copied into the state dir
- Galera `mariadb-dump --all-databases`
- Ghost MariaDB dump
- on-demand runs of the honcho, zitadel and ghost backup CronJobs

**Smoke checks run by `move-restore.sh`:**
- Longhorn volumes healthy
- no stuck pods
- OpenBao unsealed
- scm, blog, auth and luna URLs answer
- Hermes uses the base venv (the `installs/` trap)
- Luna and Cheshire reply through their bridges

**Not touched:**
- Galera (operator-managed, local-path): it stops with the nodes and the mariadb-operator's Galera recovery
  bootstraps from the most advanced node at start.
- local-path workloads: OpenBao, Prometheus, Paperclip, Uptime Kuma, Hombre.
- Host services (netbird, Ziti routers, Docker) stop and start with the OS.

**Manual after restore:**
- Send Mickey a Signal message.
- Run `netbird status` on a node.
- The NetBird discovery log continues by itself (`kube-system/nb-discovery`).

## BMC firmware upgrade

Do it **after the move with all four node slots powered off**, before step 3:
- A BMC upgrade reboots the BMC, and the BMC owns slot power, so nothing should be running when it does.
- It doesn't need the cluster, and node1 can't reach the BMC directly anyway (asymmetric path through OPNsense, see
  `k3s-cluster-notes.md`).

Steps:
1. Back up the BMC settings.
2. Upgrade from the BMC web UI (Upgrade Firmware → file → verify → reboot).
3. Check that the BMC is back at `192.168.1.223` and the node **USB mode is not "Flash"**. Flash mode leaves a node
   stuck in maskrom; see the node2 rebuild notes.
4. Power the four slots on from the BMC.
5. Run `move-restore.sh` once node1 is reachable.

If the upgrade fails, the v2 firmware falls back to the previous image, so the nodes can still be powered on.

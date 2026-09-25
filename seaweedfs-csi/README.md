# SeaweedFS CSI Driver

## Overview

The SeaweedFS CSI driver allows Kubernetes workloads to consume SeaweedFS storage
as native PersistentVolumeClaims. It creates a `seaweedfs-storage` StorageClass that
provisions directories on the SeaweedFS filer, enabling `ReadWriteMany` access from
multiple pods — something Longhorn does not support.

This driver was added to support workloads that need shared filesystem access (e.g.
Jellyfin media storage) backed by the cluster's SeaweedFS installation.

## StorageClass

| Detail | Value |
|---|---|
| Name | `seaweedfs-storage` |
| Provisioner | `seaweedfs-csi-driver` |
| Access Modes | `ReadWriteOnce`, `ReadWriteMany` |
| Volume Expansion | Supported |
| Binding Mode | `Immediate` |

## Architecture

The CSI driver deploys three components:

| Component | Type | Purpose |
|---|---|---|
| `seaweedfs-controller` | Deployment | Handles PV provisioning, attachment, and resizing |
| `seaweedfs-node` | DaemonSet | Runs on every node; mounts SeaweedFS FUSE volumes into pods |
| `seaweedfs-mount` | DaemonSet | Manages FUSE mount lifecycle per node |

All components connect to the SeaweedFS filer at `seaweedfs-filer.seaweedfs:8888`.

## Installation

```bash
kubectl apply -f seaweedfs-csi.yaml
```

Wait for all CSI pods to be ready before creating PVCs:

```bash
kubectl wait --for=condition=ready pod -n default -l app=seaweedfs-node --timeout=120s
kubectl wait --for=condition=ready pod -n default -l app=seaweedfs-controller --timeout=120s
```

> **Note:** The CSI driver deploys into the `default` namespace (upstream default).
> This is a known quirk of the upstream manifest — the driver still correctly provisions
> volumes in any namespace.

## Creating a PVC

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-shared-storage
  namespace: my-app
spec:
  accessModes:
    - ReadWriteMany
  storageClassName: seaweedfs-storage
  resources:
    requests:
      storage: 100Gi
```

The requested size is a quota hint — SeaweedFS does not enforce hard limits at the
volume level. Actual capacity is bounded by the underlying SeaweedFS cluster (~1.6 TB
usable with `replication: 001`).

## Version

| Detail | Value |
|---|---|
| CSI Driver | v1.4.12 |
| SeaweedFS filer | `seaweedfs-filer.seaweedfs:8888` |
| Source | [github.com/seaweedfs/seaweedfs-csi-driver](https://github.com/seaweedfs/seaweedfs-csi-driver) |

The manifest in this directory has two modifications from upstream:
1. `SEAWEEDFS_FILER` set to `seaweedfs-filer.seaweedfs:8888` (cluster-internal DNS)
2. Image tags pinned to `v1.4.12` (upstream manifest ships with `v1.4.5`)

## Common Commands

```bash
# CSI pod status
kubectl get pods -n default -l app=seaweedfs-node
kubectl get pods -n default -l app=seaweedfs-controller

# Verify StorageClass is registered
kubectl get storageclass seaweedfs-storage

# List PVCs using SeaweedFS
kubectl get pvc -A | grep seaweedfs-storage

# CSI controller logs (provisioning issues)
kubectl logs -n default -l app=seaweedfs-controller -c seaweedfs-csi-driver --tail=50
```

## Files

| File | Purpose |
|---|---|
| `seaweedfs-csi.yaml` | Full CSI driver manifest (ServiceAccounts, RBAC, StorageClass, DaemonSets, Deployment, CSIDriver) |

## Compatibility with SeaweedFS 4.47 (checked 2026-09-25)
Deployed: CSI driver `chrislusf/seaweedfs-csi-driver:v1.4.12` (controller + node plugin) and
`chrislusf/seaweedfs-mount:v1.4.12`, which bundles `weed mount` **4.22**. The server was upgraded
4.21 → 4.47 (see [`../seaweedfs/UPGRADE-4.47.md`](../seaweedfs/UPGRADE-4.47.md)).

- **Release notes v1.4.13–v1.4.32:** no compatibility requirements or breaking changes; since v1.4.21
  each release only bumps its bundled SeaweedFS code. **v1.4.32 (2026-09-14) bundles the 4.47 code**,
  so it is the matched release if you upgrade the driver.
- **Functional test against the 4.47 filers: pass.** Throwaway namespace `csi-compat-test`: 1 GiB RWX
  PVC on `seaweedfs-storage` → bound; busybox pod on k3-node1 mounted it, wrote a 5 MB random file, made
  a directory, renamed a file, listed; the file's sha256 was identical in the pod and when read directly
  from the filer (`/buckets/<pv>/blob.bin`). Deleting the PVC removed the PV and the filer folder (404).
  No errors in any CSI component.
- **Conclusion:** v1.4.12 works with SeaweedFS 4.47. Upgrading the driver to v1.4.32 is optional, to keep
  the mount client matched to the server; not required.

Jellyfin (`jellyfin/jellyfin-media`, 1 TiB, the only consumer): the Deployment is scaled to 0 and the
volume is **empty**, and it was already empty before the upgrade (only its folder entry exists in the
pre-upgrade filer metadata dump). The media library was probably never populated before SeaweedFS
broke on 2026-05-18.

## Upgrade to v1.4.32 (2026-09-25)
Image tags only (`seaweedfs-csi-driver` ×2, `seaweedfs-mount` ×1) in `seaweedfs-csi.yaml`, then
`kubectl apply -f seaweedfs-csi.yaml`. Checked first: live objects == this manifest (`kubectl diff` → 0
lines; no placeholders/secrets in the file); upstream's raw manifest is unchanged v1.4.12→v1.4.32 (and
stale, still pinning v1.4.5); the upstream Helm chart changes are optional features only (topology keys,
`mountExtraArgs`); new CLI flags have defaults; images published for arm64.

- **`seaweedfs-mount` uses `updateStrategy: OnDelete`** (on purpose: restarting it kills every FUSE mount on
  that node). `apply` alone does NOT update it; delete its pods one node at a time, **only when no pod
  uses a seaweedfs PVC** (check `kubectl get volumeattachments` and consumers such as Jellyfin).
- Result: controller, 3 node plugins, 3 mount pods on v1.4.32; mount client is now `weed mount` 4.47,
  matching the server. Functional PVC test repeated (write 5 MB / rename / read via filer: sha256 match;
  cleanup OK).
- Harmless noise: `duplicate port name "healthz"` warnings on apply (from upstream's manifest), and a
  one-off `Failed to remove finalizer from PV` from the csi-attacher while deleting the test PV (race with
  the deletion; the PV was gone).

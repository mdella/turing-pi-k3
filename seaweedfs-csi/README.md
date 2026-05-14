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

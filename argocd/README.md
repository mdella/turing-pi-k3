# Argo CD

GitOps controller, installed 2026-11-01. Applications live in the private `geekstyle/platform/k3s-gitops`; adoption starts with Uptime Kuma, on manual sync.

| What | Value |
|---|---|
| Version | Argo CD v3.5.6, chart `argo/argo-cd` 10.11.6, namespace `argocd` |
| URL | https://argocd.geekstyle.net, LAN and netbird only |
| Exposure | Cloudflare DNS-only A record to the private ingress IP `192.168.4.201`, no tunnel rule; cert from `letsencrypt-dns01` |
| Placement | All pods on k3-node2: it holds cluster-admin, so off node3/node4 (NetworkPolicy not enforced there) and off node1 (GitLab's memory peak) |
| Login | Zitadel SSO only, no Dex; built-in `admin` disabled 2026-11-01 |

```bash
helm upgrade argocd argo/argo-cd -n argocd --version 10.11.6 -f values.yaml -f ~/k3s-gitops/argocd/values-private.yaml
```

Break glass if Zitadel is down: set `admin.enabled: true` in `values.yaml` and upgrade, then remove `admin.password` and
`admin.passwordMtime` from Secret `argocd-secret` and restart `argocd-server`. It generates a new
`argocd-initial-admin-secret`.

## SSO

Zitadel project `argocd` has its own role `admin` and project and role checks, so only people granted it get a token.
The app is a public client using PKCE, with no client secret and redirect `/auth/callback`. Argo CD's docs also list `/pkce/verify`, but v3.5.6 runs PKCE on the server and only sends `/auth/callback`. Access comes from an RBAC line
matching the Zitadel user ID, and the default policy is no access, so a token alone gives nothing. That avoids the
org-wide Zitadel Action in Argo CD's guide, which would add a `groups` claim to every app's tokens.

The client ID and user ID are in `argocd/values-private.yaml` in the private `geekstyle/platform/k3s-gitops`. Include that
file on every Helm upgrade, or SSO stops working. The `argocd` CLI isn't set up for SSO yet.

## GitOps layout

`bootstrap/root.yaml` in `k3s-gitops` is applied once by hand. Its root app syncs only `projects/` and `apps/`, and its
project can only create Application and AppProject objects, so merging to `main` is how a system gets added. Each app's
project limits where it can deploy. New apps have no finalizer and no automated sync, and their Namespaces and PVCs are
marked `Delete=false,Prune=false`, so removing an app from Argo CD leaves the workload and data in place.

Argo CD pulls through the in-cluster GitLab address, so sync keeps working if the internet link drops. The read-only deploy
token is in OpenBao at `secret/k8s/argocd/repo-k3s-gitops` (`username`, `password`) and reaches Argo CD through ExternalSecret
`argocd/repo-k3s-gitops`, also applied by hand. To rotate it, update OpenBao; the cluster picks it up within the hour.
A deploy token only works with the username it was created with.

## Website

The website repo is the private `geekstyle/projects/public-www`, so its source and design notes are there. CI writes each new
image tag to that repo's unprotected `deploy-dev` branch, and app `public-www-dev` applies it automatically to namespace
`www-dev`. Because anyone who can push to that branch can change what runs, project `public-www` accepts only a Deployment and a
Service from it, and the namespace enforces the `restricted` Pod Security level. The namespace, pull secret and Ingress come
from protected `k3s-gitops` through app `public-www-dev-platform`. `www-dev.geekstyle.net` is LAN and NetBird only.

## Still to do

1. A bootstrap order: Argo CD pulls from GitLab, which runs on this cluster. GitLab, OpenBao, External Secrets, ingress-nginx
   and Longhorn stay under manual Helm at first, so a failure in one of them can't stop Argo CD fetching the fix.

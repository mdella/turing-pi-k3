# Argo CD

GitOps controller, installed 2026-11-01. No Applications yet, so it manages nothing.

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

## Still to do

1. Push `k3s-gitops` to scm.
2. A bootstrap order: Argo CD pulls from GitLab, which runs on this cluster. GitLab, OpenBao, ingress-nginx and Longhorn
   stay under manual Helm at first, so a failure in one of them can't stop Argo CD fetching the fix.

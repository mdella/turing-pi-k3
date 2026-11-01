# Argo CD

GitOps controller, installed 2026-11-01. No Applications yet, so it manages nothing.

| What | Value |
|---|---|
| Version | Argo CD v3.5.6, chart `argo/argo-cd` 10.11.6, namespace `argocd` |
| URL | https://argocd.geekstyle.net, LAN and netbird only |
| Exposure | Cloudflare DNS-only A record to the private ingress IP `192.168.4.201`, no tunnel rule; cert from `letsencrypt-dns01` |
| Placement | All pods on k3-node2: it holds cluster-admin, so off node3/node4 (NetworkPolicy not enforced there) and off node1 (GitLab's memory peak) |
| Login | Built-in `admin` for now; SSO to Zitadel is next, without Dex |

```bash
helm upgrade --install argocd argo/argo-cd -n argocd --create-namespace --version 10.11.6 -f values.yaml
```

The first admin password is in Secret `argocd/argocd-initial-admin-secret`. Delete that Secret after changing the
password or moving to SSO.

## Still to do

1. SSO through Zitadel, then disable the local admin.
2. A private GitOps project on scm.geekstyle.net.
3. A bootstrap order: Argo CD pulls from GitLab, which runs on this cluster. GitLab, OpenBao, ingress-nginx and Longhorn
   stay under manual Helm at first, so a failure in one of them can't stop Argo CD fetching the fix.

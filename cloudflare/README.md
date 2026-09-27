# Cloudflare Tunnel — geekstyle.net → k3s

The cluster sits behind Starlink CGNAT, so nothing can be port-forwarded in. A **Cloudflare
Tunnel** gets around that: `cloudflared` pods in the cluster dial *out* to Cloudflare and
Cloudflare sends matching public traffic back down those connections.

```
browser ──https──▶ Cloudflare edge (TLS, WAF, Access) ══tunnel══▶ cloudflared pods
                                                                      │ http
                                         ingress-nginx (Host routing) ◀┘  (or a direct origin)
                                                                      │
                                                                  k8s Service
```

| Detail | Value |
|---|---|
| Cloudflare account | the dedicated geekstyle.net account (not the old shared one) |
| Tunnel | `k3s-geekstyle`, **remotely managed** (routing rules live in Cloudflare, not in a local config file) |
| Connector | `cloudflared.yaml` — Deployment, 2 replicas spread across nodes, PDB, pinned image |
| Transport | QUIC (UDP 7844) outbound; falls back to HTTP/2 over 443. No OPNsense changes. |
| Default origin | `http://ingress-nginx-controller.ingress-nginx.svc.cluster.local:80` (Host header preserved) |
| Zone settings | SSL "Full", Always Use HTTPS on, min TLS 1.2 |

## Install

```bash
kubectl create namespace cloudflared
# token: dashboard → Zero Trust → Networks → Tunnels → k3s-geekstyle → install, or
#        API GET /accounts/<acct>/cfd_tunnel/<id>/token
kubectl -n cloudflared create secret generic tunnel-token --from-literal=TUNNEL_TOKEN=<token>
kubectl apply -f cloudflared.yaml
kubectl -n cloudflared logs deploy/cloudflared | grep "Registered tunnel connection"
```

## Publish a hostname (the repeatable pattern)

1. **k8s Ingress** for the host (ingressClass `nginx`, backend = the app's Service). No TLS
   block — TLS terminates at Cloudflare.
2. **Tunnel rule** — add `{hostname, service}` *above* the final `http_status:404` catch-all
   (dashboard: Zero Trust → Networks → Tunnels → k3s-geekstyle → Public hostnames, or API
   `PUT /accounts/<acct>/cfd_tunnel/<id>/configurations` with the full ingress list).
   Normal apps use the ingress-nginx origin above. Exceptions:
   - apps needing end-to-end HTTP/2 / gRPC (Zitadel) → point at their Service directly with
     `originRequest.http2Origin: true`
   - host-level services (Hermes dashboard on node1) → `http://<node-ip>:<port>`
3. **DNS** — proxied CNAME `<host>` → `<tunnel-id>.cfargotunnel.com`.
4. **App config** — the app's public URL becomes `https://<host>`; tell it it's behind a
   TLS-terminating proxy (e.g. GitLab `listen_https=false`).
5. Apps without their own login → put a **Cloudflare Access** application in front.

`originRequest.connectTimeout` etc. take **numbers (seconds)** in the API, not `"30s"`.

## Operations

- Health: `kubectl -n cloudflared get pods`; API `GET /accounts/<acct>/cfd_tunnel/<id>` → `status: healthy`, connection count.
- Upgrade: bump the image tag in `cloudflared.yaml` (keep `--no-autoupdate`), apply; the PDB keeps one connector up.
- Token rotation: regenerate in the dashboard/API, replace the Secret, `kubectl -n cloudflared rollout restart deploy/cloudflared`.
- Limits (free plan): 100 MB max request body (big git pushes/LFS via LAN/netbird instead).

## Published hostnames

| Host | Origin | Auth |
|---|---|---|
| `scm.geekstyle.net` | ingress-nginx → gitlab | GitLab login (sign-up off, admin 2FA), SSO via Zitadel planned |
| `auth.geekstyle.net` | `^/ui/v2/login` → zitadel-login:3000; rest → zitadel:8080 (h2c) | Zitadel itself |

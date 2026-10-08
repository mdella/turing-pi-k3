# Luna — second Hermes assistant (https://luna.geekstyle.net)

A plain, general-purpose assistant for the owner **and other people**, built so that a Luna user gets a chat window
and nothing else — no Hermes dashboard, no host access, no access to Mickey or to any homelab app.

```
browser ─▶ Cloudflare Access (login: Zitadel) ─▶ tunnel k3s-geekstyle ─▶ ingress-nginx ─▶ Open WebUI (ns luna)
        ─▶ bridge sidecar (nginx 127.0.0.1:8080: adds API key + per-user session key)
        ─▶ Hermes API server on k3-node1 (192.168.4.101:8642) /p/luna/v1 ─▶ Hermes profile "luna"
```

## Why not the Hermes dashboard?

The Hermes dashboard is an **owner console**: its chat can be scoped to *any* profile (incl. `default` = Mickey with
terminal/file tools) and it has host file/git/ops/config/env routers. Anyone able to log in to *a* dashboard
effectively controls Hermes on node1 (sudo + cluster admin). So Luna runs **headless** and the multi-user front end is
a separate Open WebUI.

## Components

| Piece | Where | Notes |
|---|---|---|
| Hermes profile `luna` | node1 `~/.hermes/profiles/luna` | `hermes profile create luna --clone`, then: own `SOUL.md` (plain assistant "Luna", discretion between users), Mickey's persona skill + local memories removed, own Honcho workspace `luna` (`honcho.json`), no `dashboard:` block |
| Tools | `platform_toolsets.api_server` | **chat-only**: clarify, memory, skills, todo, tts, vision, web. `tool_search`/`tool_call` only index tools inside that set — tested: no terminal/shell/file/code tool is reachable |
| API server | multiplexed gateway (`hermes-gateway.service`) | `~/.hermes/.env`: `API_SERVER_ENABLED=true`, `API_SERVER_HOST=192.168.4.101`, `API_SERVER_PORT=8642`, `API_SERVER_KEY` (default profile, unused by anything). `/p/luna/` only accepts **luna's own** `API_SERVER_KEY` (`profiles/luna/.env`); named profiles fail closed. Default profile's `api_server` toolset is also chat-only (defense in depth). |
| Front end | `luna.yaml` (ns `luna`) | Open WebUI **v0.11.4** (pinned digest; upgraded from v0.9.5 2026-10-08), Longhorn PVC, `Recreate`, avoids node1/node4. SSO only, sign-up only via OIDC, no login form; web search / image gen / code exec / API keys / community sharing off |
| Bridge | sidecar in the same pod | injects `Authorization: Bearer <luna key>` (Open WebUI never holds it) and maps Open WebUI's `X-OpenWebUI-User-Id` → `X-Hermes-Session-Key: owui:<id>` ⇒ **separate Luna memory per person**; users can't forge it (set server-side from their authenticated account) |
| Login | Zitadel project **`luna`** (role `user`, role + project check on) | app "Luna (Open WebUI)", redirect `https://luna.geekstyle.net/oauth/oidc/callback`. Separate from project `homelab`, so a Luna grant opens no homelab app |
| Edge | Cloudflare Access app `luna.geekstyle.net` | login method Zitadel, policy = allowed emails, 7-day sessions; tunnel rule → ingress-nginx; proxied CNAME |

Secrets (never committed): `luna/luna-webui-oidc` (OAUTH_CLIENT_ID/SECRET, WEBUI_SECRET_KEY), `luna/luna-hermes-api`
(HERMES_API_KEY = luna's `API_SERVER_KEY`).

## Adding a person

1. Zitadel: they sign in once at https://auth.geekstyle.net with Google (creates their user), then grant them project
   **luna** → role **user** (console → Projects → luna → Authorizations, or API `POST /management/v1/users/<id>/grants`).
2. Cloudflare Access: add their email to the app's allow policy (Zero Trust → Access → Applications → Luna).
3. They open https://luna.geekstyle.net → Access → Zitadel/Google → Open WebUI "Sign in". Open WebUI creates their
   account with role `user`. (The **first** account ever created in this Open WebUI becomes its admin — the owner signs in
   first.)

To remove someone: delete the Zitadel grant + the Access email (and optionally the Open WebUI user).

## Operations

```bash
kubectl -n luna get pods                                   # 2/2: open-webui + bridge
kubectl -n luna exec deploy/luna-webui -c open-webui -- curl -s 127.0.0.1:8080/v1/models   # → ["luna"]
hermes -p luna chat                                        # owner CLI on node1 (full CLI toolset, owner only)
```

- `hermes update` restarts the gateway (Mickey + Luna API). After updating, re-check `curl -H "Authorization: Bearer
  <luna key>" http://192.168.4.101:8642/p/luna/v1/models`.
- Rotating the luna API key: new `API_SERVER_KEY` in `profiles/luna/.env` → restart `hermes-gateway` (check the Signal
  delivery ledger first) → update Secret `luna-hermes-api` → `kubectl -n luna rollout restart deploy/luna-webui`.
- Upgrading Open WebUI: bump the digest deliberately (one-way DB migrations; back up the PVC's `webui.db` first).
  v0.11 added an SSO on/off switch `ENABLE_OAUTH` (default on) — pinned `true` in the manifest since there is no
  login form. The image is several GB; a CDN reset mid-pull leaves the pod in ImagePullBackOff (and `Recreate`
  means Luna is down meanwhile) — pre-pull with `k3s crictl pull <image@digest>` on the target node first.

## Verified 2026-10-07

Key isolation (luna key → `/p/luna` 200; luna key → default 401; default key → `/p/luna` 401; no key 401); Luna answers
as Luna and reports no shell/file access; `tool_call` escape attempt finds nothing; bridge → `["luna"]`; Open WebUI auth
on / login form off / sign-up off; Zitadel accepts the https redirect; Access enforces on luna.geekstyle.net.

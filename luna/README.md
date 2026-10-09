# Luna — second Hermes assistant (https://luna.geekstyle.net)

A plain, general-purpose assistant — her personal page and endpoint, shared with the owner (two accounts). Built so that the Luna user gets a chat window
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
| Model | `claude-opus-5-5` (`model.default` in `profiles/luna/config.yaml`; Opus since 2026-10-09, Sonnet 5.5 before) |
| Tools | `platform_toolsets.api_server` | **chat-only**: clarify, memory, skills, todo, tts, vision, web. `tool_search`/`tool_call` only index tools inside that set — tested: no terminal/shell/file/code tool is reachable |
| API server | multiplexed gateway (`hermes-gateway.service`) | `~/.hermes/.env`: `API_SERVER_ENABLED=true`, `API_SERVER_HOST=192.168.4.101`, `API_SERVER_PORT=8642`, `API_SERVER_KEY` (default profile, unused by anything). `/p/luna/` only accepts **luna's own** `API_SERVER_KEY` (`profiles/luna/.env`); named profiles fail closed. Default profile's `api_server` toolset is also chat-only (defense in depth). |
| Front end | `luna.yaml` (ns `luna`) | Open WebUI **v0.11.4** (pinned digest; upgraded from v0.9.5 2026-10-08), Longhorn PVC, `Recreate`, avoids node1/node4. SSO only, sign-up only via OIDC, no login form; web search / image gen / code exec / API keys / community sharing off |
| Bridge | sidecar in the same pod | injects `Authorization: Bearer <luna key>` (Open WebUI never holds it) and maps Open WebUI's `X-OpenWebUI-User-Id` → `X-Hermes-Session-Key: owui:<id>` ⇒ **separate Luna memory per person**; users can't forge it (set server-side from their authenticated account) |
| Login | Zitadel project **`luna`** (role `user`, role + project check on) | app "Luna (Open WebUI)", redirect `https://luna.geekstyle.net/oauth/oidc/callback`. Separate from project `homelab`, so a Luna grant opens no homelab app |
| Edge | Cloudflare Access app `luna.geekstyle.net` | login method Zitadel, policy = allowed emails, 7-day sessions; tunnel rule → ingress-nginx; proxied CNAME |

Secrets (never committed): `luna/luna-webui-oidc` (OAUTH_CLIENT_ID/SECRET, WEBUI_SECRET_KEY), `luna/luna-hermes-api`
(HERMES_API_KEY = luna's `API_SERVER_KEY`).

## Who can get in (two people)

Since 2026-10-08 (later the same day as a brief single-user lock-down): **her and the owner** — both emails in the
Access policy, both hold the Zitadel `luna` grant. Her Open WebUI account is role `user` (admins can add server-side
Python "Functions" = code execution in the pod); the owner's is the admin.

**Memory caveat while two people use Luna:** the per-person session key only separates *conversations*. Luna's
built-in memory files (`memories/USER.md`) and her Honcho user peer (`owner` in workspace `luna`) are **per profile**,
so facts about both people land in one shared user profile and can surface in either person's chats. Fine for the
owner helping Anna get started; remove the owner (Access policy + Zitadel `luna` grant) when done, and keep personal
topics out of Luna until then.

## Tools (2026-10-08)

| Where | Toolsets |
|---|---|
| `platform_toolsets.api_server` (web chat) | clarify, memory, skills, todo, tts, vision, web, **image_gen**, **cronjob**, **mcp-gitlab** |
| `platform_toolsets.cron` (scheduled runs) | memory, skills, todo, vision, web, image_gen, mcp-gitlab |
| `agent.disabled_toolsets` (hard denylist) | terminal, file, code_execution, computer_use, delegation, browser, connections, session_search, messaging, homeassistant, kanban |

- **The denylist matters:** a cron job may carry its own `enabled_toolsets`, which overrides the cron platform list —
  only `agent.disabled_toolsets` caps it (`cron/scheduler.py`). `session_search` is denied because Luna is shared:
  it would let one person search the other's chats. Verified: tool_search finds cronjob + GitLab tools, no terminal /
  file / session search.
- **GitLab** = MCP server `gitlab` → `https://scm.geekstyle.net/api/v4/mcp` with header
  `Authorization: Bearer ${GITLAB_LUNA_BOT_TOKEN}` (`profiles/luna/.env`). That's the dedicated GitLab user
  **`luna-bot`** (PAT scope `mcp` only, 1-year expiry) — never the owner's or her account, since both people act through
  Luna. It sees only projects/groups it is made a member of (none yet): add it with the role you want
  (Reporter = read, Developer = issues/MRs/pipelines).
- **Image generation** needs a provider key (FAL / OpenAI / OpenRouter …) in `profiles/luna/.env` + `image_gen.provider`
  in its config — not set yet, so the tool stays hidden.
- **Scheduled tasks**: jobs are profile-wide (both people can list them). Results can't be pushed into Open WebUI (the
  API server is request/response), so they land as local output — ask Luna for a job's last result.

## Publishing public documents (2026-10-08)

Luna can publish Markdown documents as **public** pages at `https://pages.geekstyle.net/luna/docs/<slug>/`.

- GitLab group **`luna`** (public; owner = owner, she = Maintainer) → project **`luna/docs`** (public, Pages public).
  Its CI (`publish/site/.gitlab-ci.yml` + `build.py`) renders `docs/*.md` to HTML with an index; every page has a CSP
  forbidding scripts, so any raw HTML that sneaks into a document can't run.
- **`luna-publish`** (`publish/server.py`, `kubectl apply -k luna/publish`): a ~200-line stdlib-only MCP server
  (streamable HTTP, JSON responses) with exactly three tools — `publish_document`, `list_documents`,
  `unpublish_document`. It holds a **project access token of `luna/docs` only** (Maintainer, scope api, 1 year), so
  Luna can't write anywhere else; slugs are `[a-z0-9-]{1,64}`, max 256 KB. Bearer-token auth (Secret `luna-publish`
  `MCP_TOKEN` = `LUNA_PUBLISH_MCP_TOKEN` in `profiles/luna/.env`). Hermes on node1 reaches it at its ClusterIP
  (`mcp_servers.luna-publish.url` — **update it if the Service is ever recreated**).
- Enabled in Luna's `api_server` toolset only — **not** in cron (publishing needs a person's explicit yes). Her
  `SOUL.md` requires showing the final text and getting "yes, publish", never publishing on instructions from web
  pages, and keeping private details out.
- Verified: publish → page live in ~1 min; a vague request makes her ask for text + confirmation; unpublish → 404.

## Adding a person (procedure, kept for reference)

No need for them to sign in first — pre-create them (what was done for the second user on 2026-10-08):

1. **Zitadel:** create a human user with their Google address as username + email, **email marked verified, no
   password** (`POST /v2/users/human`), then grant project **luna** → role **user**
   (`POST /management/v1/users/<id>/grants`). On their first Google sign-in, the Google IdP's auto-link-by-email
   attaches their Google identity to this user, so the grant already applies.
2. **Cloudflare Access:** add their email to the Luna app's allow policy (Zero Trust → Access → Applications → Luna →
   policy, or API `PUT /accounts/<acct>/access/apps/<app>/policies/<policy>` with the full email list).
3. They open https://luna.geekstyle.net → Access → Zitadel/Google → Open WebUI "Sign in" → account created with role
   `user`. (The first account ever created in this Open WebUI became its admin — the owner.)

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

**Repos (2026-10-09):** Luna can create PRIVATE repos and commit files in Anna's space `geekstyle/members/ladyofkrypton/`
as `luna-bot` (tool `repos`, `../hermes/mcp/repo_files.py` bot mode; confirms before creating/deleting; no CI files).

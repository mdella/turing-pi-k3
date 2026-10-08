# Mickey — the owner's everyday Hermes chat (https://mickey.geekstyle.net)

A **user** front end for Hermes' default profile (Sorcerer Mickey), so daily chatting doesn't happen in the admin
console. `hermes.geekstyle.net` (the Hermes dashboard) is now reserved for administration.

```
browser ─▶ Cloudflare Access (Zitadel, owner only) ─▶ tunnel ─▶ ingress-nginx ─▶ Open WebUI (ns mickey)
        ─▶ bridge sidecar (adds default-profile API key + X-Hermes-Session-Key "mickey-web:<user>")
        ─▶ Hermes API server 192.168.4.101:8642 /v1 (default profile)
```

Same pattern as `../luna/` (read that README for the design and the bridge). Differences:

| | |
|---|---|
| Profile | `default` (Mickey) — same Honcho memory as Signal / CLI |
| Tools (`platform_toolsets.api_server` in `~/.hermes/config.yaml`) | clarify, memory, skills, todo, tts, vision, web, **mcp-gitlab** (GitLab as the owner) — no terminal / file / cron |
| Login | Zitadel project **`mickey`** (role `user`, only the owner granted) + Access app "Mickey" (owner email only, 7-day sessions) |
| Secrets (never committed) | `mickey-webui-oidc` (OAUTH_CLIENT_ID/SECRET, WEBUI_SECRET_KEY), `mickey-hermes-api` (HERMES_API_KEY = `API_SERVER_KEY` in `~/.hermes/.env`) |

Admin console hardening (same day): Access session for `hermes.geekstyle.net` cut from 168h to **12h**. Possible next
step: take hermes.geekstyle.net off the public tunnel (LAN/netbird only).

Verified 2026-10-08: unauthenticated → Access login; bridge → Hermes answers as Mickey; tool_search finds GitLab tools,
no terminal / file tools.

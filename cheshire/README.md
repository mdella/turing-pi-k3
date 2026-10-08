# Cheshire — the owner's personal 1:1 assistant (https://cheshire.geekstyle.net)

Hermes profile **`cheshire`** with an Open WebUI front end — the owner's own assistant, separate from
**Sorcerer Mickey** (default profile = the multi-person Signal group assistant) and from **Luna** (Anna's assistant).
Administration stays on the Hermes CLI / the dashboard at hermes.geekstyle.net (Access session 12h).

```
browser ─▶ Cloudflare Access (Zitadel, owner only) ─▶ tunnel ─▶ ingress-nginx ─▶ Open WebUI (ns cheshire)
        ─▶ bridge sidecar (adds cheshire's API key + X-Hermes-Session-Key "cheshire-web:<user>")
        ─▶ Hermes API server 192.168.4.101:8642 /p/cheshire/v1 (profile cheshire)
```

Same pattern as `../luna/` (see its README for the bridge and key isolation).

| | |
|---|---|
| Profile | `~/.hermes/profiles/cheshire` — created `--clone-from luna`, then: Luna's memory files wiped, Luna's GitLab-bot and publish tokens removed, own `API_SERVER_KEY`, own `SOUL.md` (Cheshire: light Cheshire-Cat touch, confirms before changing GitLab) |
| Memory | Honcho workspace **`cheshire`** with its **own workspace-scoped JWT** (a cloned token for another workspace is rejected — verified) |
| Tools (`api_server`) | clarify, memory, skills, todo, tts, vision, web, image_gen (no provider key yet), cronjob, session_search, **mcp-gitlab as `cheshire-bot`** (since 2026-10-08: Maintainer in `geekstyle/members/cheshire`, Developer in `geekstyle/platform` + `geekstyle/projects` — can't push protected default branches, so changes go via MRs; PAT `hermes-cheshire-mcp`, scope `mcp`, 1 year, `GITLAB_CHESHIRE_BOT_TOKEN` in the profile `.env`; the earlier owner-account token was revoked) |
| Hard denylist | `agent.disabled_toolsets`: terminal, file, code_execution, computer_use, delegation, browser, connections, messaging, homeassistant, kanban |
| Login | Zitadel project **`cheshire`** (role `user`, owner only) + Access app "Cheshire" (owner email, 7-day sessions) |
| Secrets (never committed) | `cheshire-webui-oidc`, `cheshire-hermes-api` |

History: built first as `mickey.geekstyle.net` (a web front end on the default profile) and repurposed the same day
once it was clear Mickey is the shared Signal persona — DNS, tunnel rule, Access app and Zitadel project renamed.

Verified 2026-10-08: unauthenticated → Access; cheshire key works only on `/p/cheshire` (luna/default → 401); answers
as Cheshire; GitLab tools present (as owner), no terminal/file tools; Honcho session created in workspace cheshire.

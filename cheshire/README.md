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
| Tools (`api_server`) | clarify, memory, skills, todo, tts, vision, web, image_gen (no provider key yet), cronjob, session_search, mcp-s3, mcp-repos, **mcp-render** (diagrams/documents, 2026-10-09), **mcp-gitlab as `cheshire-bot`** (since 2026-10-08: Maintainer in `geekstyle/members/cheshire`, Developer in `geekstyle/platform` + `geekstyle/projects` — can't push protected default branches, so changes go via MRs; PAT `hermes-cheshire-mcp`, scope `mcp`, 1 year, `GITLAB_CHESHIRE_BOT_TOKEN` in the profile `.env`; the earlier owner-account token was revoked) |
| Hard denylist | `agent.disabled_toolsets`: terminal, file, code_execution, computer_use, delegation, browser, connections, messaging, homeassistant, kanban |
| Login | Zitadel project **`cheshire`** (role `user`, owner only) + Access app "Cheshire" (owner email, 7-day sessions) |
| Secrets (never committed) | `cheshire-webui-oidc`, `cheshire-hermes-api` |

History: built first as `mickey.geekstyle.net` (a web front end on the default profile) and repurposed the same day
once it was clear Mickey is the shared Signal persona — DNS, tunnel rule, Access app and Zitadel project renamed.

Verified 2026-10-08: unauthenticated → Access; cheshire key works only on `/p/cheshire` (luna/default → 401); answers
as Cheshire; GitLab tools present (as owner), no terminal/file tools; Honcho session created in workspace cheshire.

## Model, model picker, repos and public pages (2026-10-08)

- **Default model: `claude-opus-5-5`** (profile `model.default`). The web page has a **model picker**: Opus 5.5 (default),
  Sonnet 5.5, Haiku 5.5 — Open WebUI's connection `model_ids` (stored in `webui.db` config key `openai.api_configs`,
  `ui.default_models`; env `DEFAULT_MODELS` only applies to a fresh DB) and Hermes'
  `gateway.platforms.api_server.direct_model_requests: true` in the **default** profile's config (the multiplexed API server
  is shared, so per-profile `model_routes` don't work; Luna's page only sends its virtual model `luna`, so it's unaffected).
  Verified: each picker choice answers from its own model. Slash commands (`/model`) don't work through the API server.
- **Two repos Cheshire maintains** via `../hermes/mcp/repo_files.py` (stdio MCP `repos`, web chat only — not in cron):
  - `pages` = **`cheshire/docs`** (public; top-level group for the short URL) → **https://pages.geekstyle.net/cheshire/docs/**,
    built by `../pages-site/` (Markdown in `docs/*.md`, images in `docs/assets/`), writes only under `docs/`.
  - `notes` = **`geekstyle/members/cheshire/notes`** (private).
  Each repo has its own project access token (Maintainer, api, 1 year; `CHESHIRE_DOCS_TOKEN` / `CHESHIRE_NOTES_TOKEN` in
  the profile `.env`). The tool never writes CI/build files (`.gitlab-ci.yml`, `build.py`, `.gitlab/`) — a CI file runs
  code on the cluster runner. It talks to GitLab in-cluster (`http://192.168.4.201`, Host `scm.geekstyle.net`) because
  Cloudflare's bot protection 403s non-browser clients like Python urllib. SOUL.md: publish only after an explicit
  "yes, publish"; private repo maintained on request.
  Verified: note write/read/list/delete; guards (CI file, build.py, outside docs/, `..`, unknown repo, `.env` upload)
  refused; asked vaguely to publish → asks for content + confirmation; explicit publish → page live in ~1 min; cleanup.

## Agent ↔ human messaging in GitLab (2026-10-09)

Agents and humans address each other in GitLab issues: the first lines of an issue or comment are `**From:** <name>` and
`**To:** <name>`, and matching **labels** act as inboxes. Agents are purple (`#8E44AD`), humans orange (`#E67E22`), and
human names carry a `human:` prefix (`To: human:Marcos`). Participants: **Benedict Wong** (the GitLab manager, Claude Code
on node1, GitLab account `benedict-bot`), **Cheshire**, **Luna**, **human:Marcos**. New agents introduce themselves and
get their own labels. **Read receipts:** on reading, swap `To: <you>` for the gray `Read: <you>` (#95A5A6); on replying,
remove it and set `From: <you>` / `To: <them>` (label colours are global, hence separate labels). Any agent or human may open an issue, one per topic; conversations needn't stay in one thread
(issue #1 is just the reference + intro point). Changes still go through MRs labelled `for:human:mdella`. First thread: issue #1 "gitlab requests"
in `geekstyle/members/cheshire/presentations/ai/ai-infra` (the protocol plus suggested extensions: one bot account per
agent, group-level labels, status labels, inbox polling by cron, issue templates).

**benedict-bot** (created 2026-10-09): GitLab user "Benedict Wong (GitLab manager bot)", noreply email, not admin, no
group/project creation; **Maintainer on `geekstyle/members`** (all member trees), Developer on `geekstyle/platform` and
`geekstyle/projects`. PAT `benedict-gitlab-manager` (scope `api`, expires 2027-10-09) lives only in `~/.gitlab-benedict-bot`
(0600) on node1; it's used by Claude Code for GitLab-manager work (issues, MRs, CI changes) via `curl -H @headerfile`.
Created with `gitlab-rails runner` (`Users::CreateService`, `skip_confirmation`, random unshared password).

## Sandbox: shell, files, Python, GPG (2026-10-09)

Cheshire's terminal/file/code tools run in his own network-less Docker container on node1 (image
`cheshire-sandbox`), with only `/workspace` and his GnuPG keyring persistent; he has a GPG key for signing and
encrypting (public key on cheshire-bot's GitLab profile). Details: [`../hermes/sandbox/cheshire/`](../hermes/sandbox/cheshire/README.md).

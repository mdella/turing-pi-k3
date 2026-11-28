# Cheshire — the owner's personal 1:1 assistant (https://cheshire.geekstyle.net)

Hermes profile **`cheshire`** with an Open WebUI front end — the owner's own assistant, separate from
**Sorcerer Mickey** (default profile = the multi-person Signal group assistant) and from **Luna** (Anna's assistant).
Administration stays on the Hermes CLI (`kubectl -n hermes exec -it deploy/hermes -c gateway -- hermes -p cheshire chat`) / the dashboard at hermes.geekstyle.net (Access session 12h).

```
browser ─▶ Cloudflare Access (Zitadel, owner only) ─▶ tunnel ─▶ ingress-nginx ─▶ Open WebUI (ns cheshire)
        ─▶ bridge sidecar (adds cheshire's API key + X-Hermes-Session-Key "cheshire-web:<user>")
        ─▶ Hermes API server in k3s (hermes-api.hermes.svc.cluster.local:8642) /p/cheshire/v1 (profile cheshire)
```

Same pattern as `../luna/` (see its README for the bridge and key isolation).

| | |
|---|---|
| Profile | `~/.hermes/profiles/cheshire` (on the `hermes-state` volume in ns `hermes`; on node1 until 2026-10-11) — created `--clone-from luna`, then: Luna's memory files wiped, Luna's GitLab-bot and publish tokens removed, own `API_SERVER_KEY`, own `SOUL.md` (Cheshire: light Cheshire-Cat touch, confirms before changing GitLab) |
| Memory | Honcho workspace **`cheshire`** with its **own workspace-scoped JWT** (a cloned token for another workspace is rejected — verified) |
| Tools (`api_server`) | terminal, file, code_execution (run in the SSH sandbox pod `sbx-cheshire`, see below), clarify, memory, skills, todo, tts, vision, web, image_gen (no provider key yet), cronjob, session_search, mcp-s3, mcp-repos, **mcp-render** (diagrams/documents, 2026-10-09), **mcp-gitlab as `cheshire-bot`** (since 2026-10-08: Maintainer in `geekstyle/members/cheshire`, Developer in `geekstyle/platform` + `geekstyle/projects` — can't push protected default branches, so changes go via MRs; PAT `hermes-cheshire-mcp`, scope `mcp`, 1 year, `GITLAB_CHESHIRE_BOT_TOKEN` in the profile `.env`; the earlier owner-account token was revoked) |
| Hard denylist | `agent.disabled_toolsets`: computer_use, delegation, browser, connections, messaging, homeassistant, kanban (terminal, file, code_execution were removed on 2026-10-09 when the sandbox arrived) |
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

Cheshire's terminal/file/code tools run in his own network-less sandbox: since the 2026-10-11 k3s cutover the SSH
sandbox pod `sbx-cheshire` (ns `hermes`, `../hermes/k8s/sandboxes.yaml`; before that a Docker container on node1, image
`cheshire-sandbox`), with only `/workspace` and his GnuPG keyring persistent; he has a GPG key for signing and
encrypting (public key on cheshire-bot's GitLab profile). Details: [`../hermes/sandbox/cheshire/`](../hermes/sandbox/cheshire/README.md).

## Open WebUI models and user features (2026-10-15)

- **Picker:** Claude Opus 5.5 (default), Sonnet 5.5, Haiku 5.5, through `openai.api_configs` `model_ids` in `webui.db`.
  The gateway's `direct_model_requests` passes the chosen model to the `cheshire` profile, so the persona,
  memory and tools stay the same. The Arena (blind comparison) model is off.
- **Personal connections** (`direct.enable`) are on: each user can add their own OpenAI-compatible endpoint and key
  under Settings → Connections. Those calls go from the browser and don't touch Hermes.
- **Workspace models** (`user.permissions.workspace.models`) are on for role `user`, so users can save custom models
  (base model + system prompt + parameters). Workspace tools, knowledge and import/export stay **off**, because
  tools run code on the server. With `BYPASS_MODEL_ACCESS_CONTROL=true`, every model, including custom ones, is
  visible to every user of this instance.
- These settings live in `webui.db`; the env vars only seed a fresh database. A backup from before the change is in
  `/app/backend/data/webui.db.bak-20261015-173716-before-models`.

**Login (2026-10-15):** the Cloudflare Access app uses its own login, "Zitadel (cheshire)": a Zitadel app in project
`cheshire` (owner holds role `user`), not the shared homelab one, like Luna. The policy is still owner-only.

## Open WebUI 0.12.2 → 0.12.4 (2026-10-27)

0.12.4 carries security fixes (advisories published after CVE assignment); 0.12.3 skipped. Before: `webui.db` online copy
via SQLite's backup API (`webui.db.bak-20261027-152413-before-0.12.4`, integrity ok) + Longhorn snapshot
`cheshire-webui-pre-0-12-4`; image pre-pulled on node2/node3. Checked the 0.12.4 behaviour change first: "Direct Integrations off now
disables saved tool/terminal servers". Here `direct.integrations.enable` is false and no user has personal tool or terminal
servers, so nothing is lost (`direct.enable`, the personal model connections, is separate and stays on). After: `/api/version`
0.12.4, health 200, migrations clean, bridge → Hermes model list OK, and a real reply through the bridge. Skill lazy loading
(`ENABLE_SKILL_LAZY_LOADING`, new in 0.12.4) defaults to **off**.


## Open WebUI 0.13.0 (2026-11-04)

Cheshire and `chat` (ai-services) run Open WebUI 0.13.0. They are the owner's test beds for new features, so they track the newest release. Luna stays one step behind on 0.12.5 (see `../luna/README.md`).

0.13.0 ran three schema migrations (comments and reactions, tool on/off state, inbox notifications). Backups from before the upgrade: `webui.db.bak-20261104-170029-v0.12.4` on each PVC, copies in `~/backups/<ns>-webui/` on node1, and Longhorn snapshots `<ns>-webui-pre-0-13-0`.

Settings turned on 2026-11-04 on Cheshire and `chat` (stored in each `webui.db`, not the manifests): Comments (`ENABLE_COMMENTS`) and the Allow Side Chat user permission (`chat.side_chat`).

## Open WebUI 0.13.4 (2026-11-22)

Upgraded from 0.13.3 together with chat and luna. Cheshire went first. Backups, checks and rollback are in `luna/README.md` "Open WebUI 0.13.4 on all three instances".

## Scheduled-job results in the chat (2026-11-28)

**Why a bridge.** Hermes can't push a cron result into Open WebUI. Cheshire's chat reaches him through Hermes'
`api_server` platform, which only answers requests (`cron/scheduler_delivery.py` lists it in
`_NON_PUSH_ORIGIN_PLATFORMS`). Hermes' `webhook` platform is inbound only, so it can't post out either. His two price
watches had been set to Signal (blocked on every run, since his profile has no Signal) and to `local` (results saved
but never seen).

**How it works now.**
- Cheshire's jobs use `deliver: local`. Each run writes `cron/output/<job id>/<time>.md` in his profile.
- CronJob `hermes/cheshire-webui-alerts` runs every 10 minutes ([`../hermes/k8s/cheshire-webui-alerts.yaml`](../hermes/k8s/cheshire-webui-alerts.yaml)).
  It runs [`../hermes/bin/cheshire-webui-alerts.py`](../hermes/bin/cheshire-webui-alerts.py), which reads new run files
  of every `local` job and posts each real result into the owner's chat **"Cheshire alerts"** as a message from
  Cheshire, then marks the chat unread.
  - `[SILENT]` runs are skipped.
  - A failure (`[CRON_FAILURE]`) is posted only at the start of a streak.
  - A blocked run is posted once per reason.
  - Replying in that chat talks to Cheshire as usual, with the alerts as context.
- The job mounts only `profiles/cheshire/cron` of the state volume, has no service account token and a read-only
  root FS, and uses the same image as the gateway.
- The Open WebUI API key is from the owner's account. It sits in OpenBao at `secret/k8s/hermes/cheshire-webui-alerts`
  (`api_key`), written with [`../hermes/bin/set-cheshire-webui-alerts-key`](../hermes/bin/set-cheshire-webui-alerts-key)
  (hidden prompts, values only on stdin), and External Secrets syncs it into the namespace.
- **Open WebUI side** (stored in `webui.db`): Admin settings, Authentication: **API Keys** on, **API Key Endpoint
  Restrictions** on, **Allowed Endpoints** = `/api/v1/chats/<alerts chat id>`. Only for the very first run, which
  creates the chat, is `/api/v1/chats/new` allowed. Open WebUI matches the path exactly or as a prefix plus `/`, so
  the key can touch only that one chat. Persistent config means the `ENABLE_API_KEYS` env var in `cheshire.yaml` no
  longer decides this; the stored setting does.
- Cheshire's `SOUL.md` has a "Scheduled jobs" section: use `deliver: local`, reply `[SILENT]` / `[CRON_FAILURE]`, and give
  jobs the `file` toolset when they need sandbox files.

**The two price watches.**
- *NAS drive price watch* (HC560 20TB / Exos X24 24TB under $22/TB, every 6 h) had failed about 100 runs in a row.
  Scheduled runs get only the `cron` platform toolsets, which don't include `file`, so it couldn't open
  `/workspace/price-watches/nas-drives.json`. Fixed by giving the job `enabled_toolsets: [web, file]`. The `file` tools
  work in the no-network sandbox pod, and per-job lists can't go past `agent.disabled_toolsets`.
- *WD Blue SN5000 2TB under $200* (daily 15:00 UTC) changed from `signal` to `local`.
- Both were run by hand on 2026-11-28 03:13Z. Each read and updated its file; neither price qualified (`[SILENT]`).
- Backup of the jobs file: `cron/jobs.json.bak-20261128`. SOUL backup: `SOUL.md.bak-20261128-alerts`.
- **Status 2026-11-28:** live. The owner turned on API keys and stored the key. The first run (by hand, about 06:10Z) created the
  chat "Cheshire alerts" with an intro message and recorded the current run files of both price watches as already
  read. CronJob unsuspended, and its first scheduled run completed with nothing to post. Next: Allowed Endpoints narrowed
  from `/api/v1/chats/new` to the chat's id (owner, in the UI).

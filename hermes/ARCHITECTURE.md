# Hermes on k3s — architecture, decisions, secrets (as of 2026-10-30)

How the assistants (Mickey, Cheshire, Luna) are deployed, why it is built this way, and where every credential lives.
Values are never in this repo (it is public); this page names **where** they are and **what** they are for.
Detailed runbooks and incident notes stay in [`README.md`](README.md); this is the map.

## 1. The pieces

| Component | Where | What it is |
|---|---|---|
| **Gateway** (`gateway` container, Deployment `hermes`) | [`k8s/hermes.yaml`](k8s/hermes.yaml) | One Hermes Agent process (Nous Research, **v0.22.5**) serving **all three profiles** (multiplexed). Signal adapter, OpenAI-compatible API server (:8642), cron, memory, tools. |
| **Dashboard** (`dashboard` container, same pod) | `k8s/hermes.yaml` | Hermes web dashboard (:9119), owner only (Cloudflare Access + its own login). |
| **State volume** `hermes-state` (Longhorn, 20 Gi, 3 replicas) | `k8s/hermes.yaml` | `HERMES_HOME`: per-profile `config.yaml`, `.env`, `SOUL.md`, skills, `state.db` (sessions, delivery ledger), caches, the agent-browser binary. |
| **signal-cli** (Deployment) | `k8s/hermes.yaml` | Signal linked device for Mickey, JSON-RPC on :8093 (no auth → NetworkPolicy-restricted). Own PVC. |
| **Tool sandboxes** `sbx-cheshire`, `sbx-luna` | [`k8s/sandboxes.yaml`](k8s/sandboxes.yaml) | Where Cheshire's / Luna's **terminal, file and code tools run** (Hermes `ssh` terminal backend). One pod each, own PVC (workspace, GnuPG, Obsidian vault), no egress. |
| **vault-sync** sidecar (in each sandbox pod) | [`k8s/vault-sync.yaml`](k8s/vault-sync.yaml) | Syncs the person's Obsidian vault (GitLab repo, Git LFS) every minute. Holds the vault token; the agent never sees it. |
| **Shared browser** `hermes-browser` | [`k8s/browser.yaml`](k8s/browser.yaml), [`shared-browser.md`](shared-browser.md) | browserless/chromium: a fresh, throwaway Chromium per browser session over CDP; internet-only egress. |
| **Render service** `hermes-render` | [`k8s/render.yaml`](k8s/render.yaml) | Headless Chromium behind a small HTTP API for Mermaid/Markdown/HTML → SVG/PNG/PDF (`render_docs`). No egress. |
| **Mac Studio relay** | `k8s/hermes.yaml` | socat on node1/node3 → the Mac Studio's local models over netbird (`mac-studio.hermes.svc:11434`). |
| **Timers** (CronJobs) | [`k8s/timers.yaml`](k8s/timers.yaml) | Signal allowlist sync (10 min), DM cost alert (hourly), nightly signal-cli backup (encrypted). |
| **Front ends** (other namespaces) | [`../luna/`](../luna/README.md), [`../cheshire/`](../cheshire/README.md) | Open WebUI per person (`luna.`, `cheshire.geekstyle.net`), each with an nginx **bridge** sidecar to the gateway API. |
| **Memory** (other namespace) | [`../honcho/`](../honcho/README.md) | Honcho 3.4.1: per-person long-term memory. Hermes talks to it through the bundled Honcho plugin. |

Image: `registry.geekstyle.net/geekstyle/platform/hermes-image:<version>-<date>-<sha>`, built by GitLab CI from
**`geekstyle/platform/hermes-image`** (mirror: [`image/`](image/)). Same repo builds `/sandbox`, `/render`, `/signal-cli`.

## 2. How a message flows

- **Mickey on Signal:** phone → Signal servers → `signal-cli` pod → gateway (Signal adapter, profile *default*) →
  Claude (Anthropic API) ↔ tools (chat-only set) → reply via `signal-cli`. Every outbound reply is first written to
  the **delivery ledger** in `state.db`, so a restart can't lose or double-send it — hence "check the ledger before
  restarting".
- **Cheshire / Luna in the browser:** user → Cloudflare Access (Zitadel login, per-app) → Cloudflare Tunnel →
  Open WebUI (their namespace) → **bridge** sidecar (injects that profile's API key, maps the Open WebUI user id to a
  Hermes session key) → gateway `/p/<profile>/v1/chat/completions` → Claude ↔ tools. Terminal/file/code tools are
  executed **over SSH in that person's sandbox pod**; browser tools in the shared browser pod; rendering in the render pod.
- **CLI (admin):** `kubectl -n hermes exec deploy/hermes -c gateway -- hermes [-p <profile>] chat` — the full toolset.

## 3. What is shared and what is per person

**One process, three profiles.** Mickey, Cheshire and Luna are *profiles* inside the same gateway process, not separate
containers. Per profile: `config.yaml` (model, toolsets per platform, MCP servers, browser policy), `.env` (credentials),
`SOUL.md` (persona), skills, sessions, Honcho workspace. Since 0.22 a profile can only read **its own `.env`**
(secret scope) — one profile cannot see another's keys.

**Isolation is per tool sandbox.** The parts that touch untrusted input or run commands are separate pods with their own
credentials and network rules: each person's sandbox (own volume, no egress except vault-sync → GitLab), the shared
browser (internet only, nothing kept between sessions), the render service (no egress). The gateway itself still holds
all three profiles' `.env` files, which is why **Mickey's Signal side stays chat-only** and the gateway's local terminal
is admin-CLI only.

| Profile | Who | Channels | Tools (summary) | Sandbox |
|---|---|---|---|---|
| default (**Mickey**) | Signal groups + paired DMs | Signal; admin CLI | Signal: web, browser (since 10-23, persona guardrails), vision, voice, memory, skills, todo, clarify — no terminal/files/code/cron/GitLab | none (CLI uses the gateway) |
| **Cheshire** | the owner, 1:1 | cheshire.geekstyle.net | terminal, files, code, browser, image gen, cron, GitLab (cheshire-bot), S3, render, repos, Excalidraw | `sbx-cheshire` |
| **Luna** | Anna (+ owner) | luna.geekstyle.net | as Cheshire but GitLab via luna-bot only, no session_search, plus luna-publish; never owner credentials | `sbx-luna` |

## 4. Network rules ([`k8s/network.yaml`](k8s/network.yaml) + per-component files)

- Gateway API :8642 only from the two Open WebUI pods; dashboard :9119 only from cloudflared.
- Sandboxes: no egress at all except vault-sync → GitLab :80 (no DNS; GitLab's Service IP pinned via hostAliases); SSH
  in from the gateway only.
- signal-cli RPC only from the gateway and the timer jobs; egress internet only.
- Shared browser: in from the gateway only (plus a token); out to the public internet only — RFC 1918, CGNAT/netbird,
  link-local, cluster ranges and the LAN's public IPv6 prefix blocked.
- Render: no egress. Mac relay: only the gateway.
- **NetworkPolicies are not enforced on node3/node4** (cluster known issue), so anything that depends on them is
  pinned off those nodes (signal-cli, the browser).

## 5. Where the secrets are

Nothing below is in git. "PVC" = the `hermes-state` volume (`~/.hermes` inside the gateway).

| Secret | Location | Used by / for |
|---|---|---|
| Anthropic credential (`ANTHROPIC_API_KEY`, a Claude setup token) | PVC: `.env`, `profiles/cheshire/.env`, `profiles/luna/.env` | Claude for all three profiles. Rotate with [`k8s/reauth-anthropic.sh`](k8s/reauth-anthropic.sh) (updates all three, checks the ledger, restarts). |
| API server keys (`API_SERVER_KEY`) | PVC: each profile's `.env` | Authenticate the Open WebUI bridges to `/p/<profile>/`. Mirrored in Secrets **`cheshire/cheshire-hermes-api`**, **`luna/luna-hermes-api`** (`HERMES_API_KEY`) for the bridges. |
| GitLab bot tokens (`GITLAB_CHESHIRE_BOT_TOKEN`, `GITLAB_LUNA_BOT_TOKEN`, `CHESHIRE_*_TOKEN`, `LUNA_*_TOKEN`) | PVC: that profile's `.env` | GitLab MCP / repos MCP as cheshire-bot / luna-bot (scoped bot users, not the owner). |
| S3 (`HERMES_S3_ACCESS_KEY` / `_SECRET_KEY`) | PVC: Cheshire's and Luna's `.env` | SeaweedFS scoped identities for the S3 MCP. |
| Signal (`SIGNAL_ACCOUNT`, allowlists, home channel) | PVC: `.env` (allowlists rewritten by the sync timer); Secret **`hermes/hermes-signal`** (`account`) for signal-cli | Mickey's Signal identity; the linked-device keys live on the `signal-cli-data` PVC. |
| Shared browser URL + token (`BROWSER_CDP_URL`) | Secret **`hermes/hermes-browser`** (`token`, `cdp_url`) → gateway env; **and** each profile's `.env` (0.22 per-profile scope) | Browser tools → browser pod. Rotating the token = update the Secret **and the three `.env` lines**, restart both. |
| SSH keys for the sandboxes | Secrets **`hermes/hermes-ssh`** (gateway's client keys + pinned host keys), **`sbx-<p>-ssh`** (each sandbox's host key + that profile's public key only) | Gateway → sandbox terminal. Each profile's key works only on its own sandbox. |
| Vault tokens | Secrets **`hermes/sbx-cheshire-vault`**, **`sbx-luna-vault`** (`token`; GitLab project access tokens, `write_repository`, that repo only, expire 2027-10-14) | vault-sync sidecar only (not mounted in the sandbox container). |
| Timer settings | Secret **`hermes/hermes-timers`** (`age_recipient`, `alert_to`, `owner_uuid`) | Cost alert recipient, backup encryption recipient. |
| signal-cli backup key | Secret **`hermes/signal-cli-backup-key`** (`identity.txt`, `recipient`) | age-encrypted nightly backup of the Signal account. |
| Registry pull | Secret **`hermes/registry-pull`** (deploy token, `read_registry`) | Pulling hermes-image images. |
| Open WebUI login | Secrets **`cheshire/cheshire-webui-oidc`**, **`luna/luna-webui-oidc`** (Zitadel client id/secret, `WEBUI_SECRET_KEY`) | Per-app Zitadel login (own Zitadel project per front end). |
| luna-publish | Secret **`luna/luna-publish`** (`GITLAB_TOKEN`, `MCP_TOKEN`) | Luna's publishing MCP service. |
| Honcho | Secret **`honcho/honcho-secrets`** (JWT secret, DB URI, its own Anthropic API key, OpenAI key slot, Postgres password); Hermes's Honcho key in `~/.hermes/honcho.json` (PVC) | Memory server; the Hermes key is scoped to the `hermes` workspace. |
| Hermes dashboard password | PVC (set with `/opt/geekstyle/bin/set-dashboard-password`) | Owner-only dashboard. |

**Why `.env` on the PVC rather than Kubernetes Secrets:** the Signal allowlist sync rewrites `.env` at runtime and
Hermes manages its own `.env` (e.g. `hermes auth`), so a Secret-rendered file would be overwritten or undo those
changes. Moving the static values into **OpenBao + External Secrets** (already running for other apps) is the planned
next step; it needs the owner's OpenBao login.

## 6. What we added on top of upstream Hermes

All in **`geekstyle/platform/hermes-image`** unless noted.

| Addition | Where | Why |
|---|---|---|
| `patches/signal-local.patch` | image | Signal **group observer** (unaddressed group messages kept as ephemeral context + daily digests), **name trigger** ("Mickey" counts as a mention), per-chat `channel_prompts`, **partial-delivery fix** (one dead group member no longer causes duplicate replies), Haiku **5.5** as the auxiliary default, `/p/<profile>/` virtual-model fix for the API server. Since 0.22 these target `plugins/platforms/signal/adapter.py` (3-way merged). |
| `patches/ssh-no-sync-back.patch` | image | Stops the SSH backend copying sandbox files back over the gateway's tree. |
| Bundled **Honcho plugin** (pinned commit) + `honcho-ai` 2.2.0 | image `Dockerfile` | Memory provider at a reviewed pin; bundled in-tree so 0.22's runtime "install from the catalog" never runs (the tree is read-only). |
| Extras `ddgs`, `edge-tts` | image | Web search and TTS without runtime installs. |
| Local MCP servers `s3_store.py`, `repo_files.py`, `render_docs.py` (+ vendored Mermaid, sha512-checked) | image `local-mcp/` → `/opt/geekstyle/local-mcp` | S3 buckets, read-only repo browsing, rendering. |
| Timer scripts `signal-allowlist-sync.py`, `dm-cost-alert.py`, `set-dashboard-password` | image `bin/` | Allowlist = members of the owner's Signal groups; cost alert on DM spend. |
| Sandbox image (git, git-lfs, pandoc, poppler, pymupdf, tesseract + ocrmypdf, docx/pptx/xlsx libs, sshd) | image `sandbox/` | The tools' runtime for Cheshire/Luna. |
| Render image, signal-cli image | image `render/`, `signal-cli/` | As above; both now remove the eMudhra-compromised root (`ca-distrust.sh`, CVE-2026-111943). |
| agent-browser 0.26.0 | PVC `~/.hermes/tools` (installed via Hermes's package manager, sha256 from its lockfile) | Browser client; not yet baked into the image. |
| Personas (`SOUL.md`), skills (e.g. `sorcerer-mickey`, Excalidraw), MCP config | PVC, per profile | Behaviour; Mickey's SOUL.md includes the browsing guardrails. |
| Open WebUI bridges | [`../luna/luna.yaml`](../luna/luna.yaml), [`../cheshire/cheshire.yaml`](../cheshire/cheshire.yaml) | Key injection + per-user session mapping. |

## 7. Decisions and requirements (and why)

1. **Move from node1 docker/systemd to k3s (2026-10-11).** HA (pods reschedule in 30 s), replicated state (Longhorn),
   NetworkPolicies, Secrets, reproducible images from CI. Rollback scripts kept (`k8s/rollback.sh`).
2. **Single gateway replica, Recreate strategy.** The gateway owns `state.db`, cron and the Signal session; two copies
   would double-reply or break the Signal link. Same for signal-cli (one linked device).
3. **Multiplexed gateway, per-profile isolation.** One process is cheaper and is now upstream's default; isolation comes
   from per-profile secret scopes and per-person sandboxes.
4. **Tools in sandboxes over SSH, not in the gateway.** Untrusted work (commands, files, code) never runs where every
   profile's credentials live; each sandbox has no egress.
5. **Signal = chat-only.** Group members can talk to Mickey, so he gets no terminal/files/code/cron/GitLab on Signal.
   Browser added 2026-10-23 by owner decision, with persona guardrails.
6. **Luna never gets owner credentials.** GitLab via luna-bot only; dashboard is owner-only; no session_search (would
   expose one user's chats to the other).
7. **Per-app Zitadel logins** for the front ends: the shared "Zitadel (geekstyle)" login's app lives in the admin
   project, so non-admins got `GrantRequired` (shown as "unknown error"); a separate project and login per front end
   also means a Luna grant opens nothing else.
8. **One shared browser pod**, fresh browser per session (no cookies or logins shared or kept), internet-only — rather
   than a browser in the gateway (next to the secrets) or one per user.
9. **Pinned everything:** images by digest, upstream base by digest, plugin by commit, downloads by sha256; CI smoke
   tests prove patches apply and the gateway boots before anything ships.
10. **Check the delivery ledger before every gateway restart.** Recreate restarts are ~30 s; the ledger prevents lost
    or duplicated Signal replies.
11. **Owner keeps the keys.** Passwords/tokens are typed by the owner (never in chat); merges to `main` are the
    owner's; the GitLab bot (benedict-bot) opens MRs only.
12. **Public repo, no secrets.** Manifests carry placeholders where needed (e.g. the LAN IPv6 prefix in `browser.yaml`).
13. **Keep all session history** (`sessions.auto_prune: false`, owner decision 2026-10-27).
14. **Hermes 0.22 requirements** (from the 0.22.5 upgrade): `bot_desktop.placement: gateway`; `BROWSER_CDP_URL` in
    every profile's `.env`; browser pod concurrency 6 (two CDP connections per task); `shareProcessNamespace: true`
    (zombie reaping).

## 8. Repos and files

- GitLab **`geekstyle/platform/hermes-image`** — images (gateway, sandbox, render, signal-cli), patches, local MCP, timers.
- GitHub **`turing-pi-k3`** — `hermes/k8s/*.yaml` (everything deployed), `hermes/README.md` (runbooks, incidents,
  upgrade logs), `hermes/shared-browser.md`, `hermes/image/` (mirror of hermes-image), `luna/`, `cheshire/`, `honcho/`.
- GitLab **`geekstyle/members/cheshire/vault`**, **`geekstyle/members/ladyofkrypton/vault`** — the Obsidian vaults.
- Upstream: `nousresearch/hermes-agent` (image) / `NousResearch/hermes-agent` (source); Honcho plugin
  `plastic-labs/honcho` (`hermes-plugin-honcho/`).

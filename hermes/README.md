# Hermes Agent: "Sorcerer Mickey", Cheshire and Luna in k3s (ns `hermes`)

[Hermes Agent](https://github.com/NousResearch/hermes-agent) (Nous Research) runs in the k3s namespace **`hermes`**
(since the cutover on 2026-10-11; before that it ran as host systemd units on k3-node1, see
[Pre-k3s (node1, rollback only)](#pre-k3s-node1-rollback-only)). The default profile is
**Sorcerer Mickey**, a personal assistant reachable from **Signal** (DM + group chats); he thinks with
**Claude Sonnet 5.5** and remembers through the self-hosted **Honcho** (`../honcho/`). The same multiplexed gateway
also serves the **Cheshire** and **Luna** profiles to their Open WebUI front ends. Set up 2026-09-24.

> Public repo: phone numbers, the Signal group ID, Signal UUIDs, the Honcho tokens and the Anthropic key are
> **not** in these notes. They live only in the profiles' `.env`/`honcho.json` on the `hermes-state` volume and in
> out-of-band Secrets (placeholders below).

**Paths.** Inside the gateway and dashboard containers `HERMES_HOME=/home/ubuntu/.hermes` (Longhorn PVC
`hermes-state`), so `~/.hermes/...` in the sections below means that path **in the pod**. node1's own `~/.hermes` is
the frozen pre-cutover copy kept for `k8s/rollback.sh`. **Do not run `hermes` on node1**: it would act on stale state.

## At a glance (k3s)
| Part | Value |
|---|---|
| Hermes | image `registry.geekstyle.net/geekstyle/platform/hermes-image:0.21.6-<date>-<sha>` (upstream v0.21.6 + `patches/`, built from [`image/`](image/)); command `hermes` in the container |
| Gateway + dashboard | Deployment `hermes` (containers `gateway`, `dashboard`), 1 replica, Recreate, prefers node2/node3 (runs on node2) |
| State | PVC `hermes-state` (Longhorn, 20 Gi) mounted at `/home/ubuntu/.hermes` |
| Persona | `~/.hermes/SOUL.md` (copy: [`SOUL.md`](SOUL.md)); original saved as `SOUL.md.orig` |
| Model | `claude-sonnet-5-5` (since 2026-10-08; was `claude-sonnet-5`) (provider `anthropic`), working context capped at 200K (`model.context_length`) |
| Memory | Honcho workspace `hermes` via `http://honcho-api.honcho.svc.cluster.local:8000` (in-cluster; Cheshire and Luna use their own workspaces). Peers: `mdella` (owner), `sorcerer-mickey` (the bot), `signal_<uuid>` (other Signal users) |
| Signal | dedicated number, `signal-cli` 0.14.8 daemon: Deployment `signal-cli` (PVC `signal-cli-data`, runs on node2; required **not** on node3, see NetworkPolicy caveat), Service `signal-cli.hermes.svc:8093` |
| Tool sandboxes | `sbx-cheshire`, `sbx-luna` (SSH backend, node3), see [`sandbox/ssh/`](sandbox/ssh/) |
| Render | `hermes-render` Service `:8080` (node3) for `render_docs` |
| Mac Studio | `mac-studio-relay` → Service `mac-studio.hermes.svc:11434` (node1/node3) |
| Timers | CronJobs `hermes-allowlist-sync` (10 min), `hermes-dm-cost-alert` (hourly), `signal-cli-backup` (03:10 UTC); [`k8s/timers.yaml`](k8s/timers.yaml) |
| Public | https://hermes.geekstyle.net → tunnel → Service `hermes-dashboard:9119` (Access + OIDC) |

## k3s deployment (current, since 2026-10-11)

| Piece | Where | Notes |
|---|---|---|
| Images | GitLab `geekstyle/platform/hermes-image` (id 10; mirror [`image/`](image/)) | CI: kaniko, MR builds w/o push, `main` pushes + smoke-tests. `hermes-image` (gateway/dashboard), `/signal-cli`, `/sandbox`, `/render` |
| Gateway + dashboard | `k8s/hermes.yaml` deploy `hermes` (2 containers) | single replica, Recreate, uid 1000, ro rootfs, `HERMES_HOME=/home/ubuntu/.hermes` on Longhorn PVC `hermes-state` (20 Gi); 30 s not-ready/unreachable tolerations; prefers node2/3 |
| signal-cli | `k8s/hermes.yaml` deploy `signal-cli` | own PVC (copied from node1's `~/.local/share/signal-cli`), RPC only from gateway + timer jobs, egress internet only; **temporarily required off node3** (no NetworkPolicy enforcement there) |
| Tool sandboxes | `k8s/sandboxes.yaml` `sbx-cheshire`, `sbx-luna` | SSH backend (see `sandbox/ssh/`); per-profile key + pinned host key (Secrets `hermes-ssh`, `sbx-<p>-ssh`); PVC holds `/workspace` + GnuPG; no egress |
| Render | `k8s/render.yaml` deploy `hermes-render` | Chromium behind a tiny HTTP API; `render_docs` uses it when `RENDER_URL` is set; flag allowlist; no egress |
| Mac Studio | `k8s/hermes.yaml` `mac-studio-relay` | socat pinned to node1/node3 → `mac-studio.hermes.svc:11434` |
| Timers | `k8s/timers.yaml` CronJobs (**active** since cutover) | allowlist sync (restarts the gateway via a Role limited to `patch deploy/hermes`), DM cost alert, signal-cli backup straight to the replicated PVC (retired `/var/backups` + the off-node copy job, which stays suspended in `k8s/signal-cli-backup.yaml`) |
| Network | `k8s/network.yaml` | API (8642) only from Luna/Cheshire webui pods; dashboard (9119) only from cloudflared (tunnel → Service, not the LAN ingress) |
| Config rewrite | `k8s/migrate_config.py` | idempotent, asserted text edits: Honcho → in-cluster, signal-cli Service, API host 0.0.0.0, Mac relay, docker→ssh terminal, MCP paths → `/opt/geekstyle`, render → service, luna-publish → DNS |

**Image notes.** Upstream `nousresearch/hermes-agent:v0.21.6` (digest-pinned) + `patches/` (build fails if a hunk stops
applying). Honcho memory left core in 0.21.6 → bundled at a pinned plastic-labs/honcho commit + `honcho-ai==2.2.0`;
`ddgs`, `edge-tts` baked; MCP servers and timer scripts under `/opt/geekstyle`; no s6 (pods run `hermes gateway run` /
`hermes dashboard` directly). `HERMES_WRITE_SAFE_ROOT=/home/ubuntu/.hermes:/workspace:/tmp` (upstream's guard also
applies to the SSH sandboxes' `/workspace`). **Upgrading Hermes = a new image** (see [`image/README.md`](image/README.md)),
not `hermes update` / `/update`. The gateway must keep running from the image's `/opt/hermes/.venv`: `~/.hermes/installs`
is a root-owned empty dir on purpose (see the 2026-10-11 regression below).

**Secrets.** The profiles' `.env` files live on the state volume (as on node1's disk): the allowlist sync rewrites
`SIGNAL_*ALLOWED*` in `.env`, so rendering `.env` from a Secret would undo it. OpenBao/ESO for these values is a later
step (needs the owner's OpenBao login). Out-of-band Secrets: `registry-pull` (deploy token `k3s-hermes-pull`),
`hermes-signal`, `hermes-ssh`, `sbx-cheshire-ssh`, `sbx-luna-ssh`, `hermes-timers`, `signal-cli-backup-key`. k3s
secrets-encryption at rest is **off** (cluster-wide).

**NetworkPolicy caveat.** k3-node3 and k3-node4 do not enforce NetworkPolicies (root cause: the NetBird routing-peer
fwmark lets pod traffic bypass kube-router's chains; fix planned in `../netbird/PLAN-opnsense-router.md`). So signal-cli,
whose RPC has no auth, carries a temporary `NotIn k3-node3` affinity; the sandboxes (SSH key auth + host-key pinning),
render and the Mac relay run on node3 regardless.

## Operations
```bash
H="kubectl -n hermes exec -it deploy/hermes -c gateway --"
$H hermes chat                                # talk to Mickey in a terminal (full tools; runs inside the pod)
$H hermes -p luna chat                        # same for a named profile
$H hermes honcho status                       # memory link
$H hermes pairing list ; $H hermes pairing approve signal <CODE>
kubectl -n hermes get pods -o wide            # hermes, signal-cli, sbx-*, hermes-render, mac-studio-relay
kubectl -n hermes logs deploy/hermes -c gateway -f      # gateway logs (dashboard: -c dashboard)
kubectl -n hermes logs deploy/signal-cli -f
kubectl -n hermes rollout restart deploy/hermes         # after config/.env/SOUL.md changes (or /restart in chat); Recreate = brief outage
$H curl -s http://signal-cli.hermes.svc:8093/api/v1/rpc -d '{"jsonrpc":"2.0","id":1,"method":"listGroups"}'   # groups Mickey is in
kubectl -n hermes get cronjob                 # timers; last runs: kubectl -n hermes get jobs
```
Check the delivery ledger is empty of pending/failed rows before restarting after a delivery problem (see Gotchas).
Never scale `hermes` or `signal-cli` above 1, and never start node1's units while the pods run (double replies, broken
Signal link). Rollback to node1: [`k8s/rollback.sh`](k8s/rollback.sh); anything said since the cutover lives only in
the k3s volumes.

**Obsidian vaults (2026-10-15).** One private vault repo per person: `geekstyle/members/cheshire/vault` (Marcos ↔
Cheshire) and `geekstyle/members/ladyofkrypton/vault` (Anna ↔ Luna). In each sandbox pod, a `vault-sync` sidecar
([`k8s/vault-sync.yaml`](k8s/vault-sync.yaml)) commits the agent's edits, rebases and pushes every 60 s. A conflict puts
the agent's version on `conflict/<UTC time>`, and `main` keeps the human's. The agent sees the work tree at
`~/Documents/Obsidian Vault`, the built-in `obsidian` skill's default path. The git dir, the push token (project
access token, write_repository, one repo, expires 2027-10-14; Secret `sbx-<profile>-vault`) and the sidecar's scratch
dir are not mounted in the agent's container. The sandboxes' only egress is GitLab :80 (no DNS; the Service IP is
pinned via hostAliases, so update it if the `gitlab` Service is ever recreated). The gateway's `HERMES_WRITE_SAFE_ROOT`
adds the vault path, otherwise file tools refuse to write there. Humans: clone the repo in Obsidian with the Obsidian
Git plugin (auto pull/push). Since 2026-10-17, images, PDFs, audio and video go to Git LFS (`.gitattributes` in each vault; the sandbox image has `git-lfs`, hermes-image !5), so photos don't bloat git history. Clients need git-lfs too: Git for Windows includes it; macOS needs `brew install git-lfs && git lfs install`. HEIC photos don't display in Obsidian on Windows, GitLab or for the agents, so use JPG. Mickey has no vault, since he stays chat-only.

**Web page reading.** `web.search_backend: ddgs` alone leaves `web_extract` without a backend: ddgs is search-only,
and because the ddgs package is installed, Hermes's keyless fallback is never reached ("ddgs is a search-only backend
and cannot extract URL content"). Since 2026-10-14 all three configs (`~/.hermes/config.yaml` plus both profiles') also
set `web.extract_backend: firecrawl`, which is Firecrawl's anonymous free tier: no key, rate-limited, and the URLs the
assistants read go to Firecrawl. Exa, Parallel and Keenable free tiers also worked when tested. Config is reread when
the file changes, so no restart is needed. Upgrade path: a paid key (`FIRECRAWL_API_KEY`), or self-hosted Firecrawl
(`FIRECRAWL_API_URL`).

**Anthropic login (401 "OAuth access token has been revoked").** Mickey, Cheshire and Luna share one Claude
setup token (`sk-ant-oat01-…`) as `ANTHROPIC_API_KEY` in `~/.hermes/.env` and both profiles' `.env` — not the
`hermes auth` pool, so `hermes auth add anthropic` doesn't fix it. Make a new one with `claude setup-token` (any machine
with Claude Code; browser login to the Claude account), then on node1 run
[`k8s/reauth-anthropic.sh`](k8s/reauth-anthropic.sh): silent prompt, test call, swaps all three, ledger check, restart.

New group → add Mickey on the phone → get its ID with `listGroups` → the allowlist sync picks up groups where the owner
is admin within 10 min (manual: append to `SIGNAL_GROUP_ALLOWED_USERS` in `~/.hermes/.env`, comma-separated, **no inline
comment on that line**, then restart the gateway).

**Deleting Mickey's posts ("delete for everyone", ~24 h window).** Hermes doesn't store Signal sent-timestamps, so:
1. Stop the gateway (`kubectl -n hermes scale deploy/hermes --replicas=0`; also stops him reacting); listen from a pod
   allowed by the signal-cli NetworkPolicy (label `hermes.geekstyle.net/signal-client: "true"`):
   `curl -sN http://signal-cli.hermes.svc:8093/api/v1/events > events.log`
2. React with any emoji to each post to delete — each reaction carries `targetSentTimestamp` of the reacted-to message.
3. For each timestamp: `{"jsonrpc":"2.0","id":1,"method":"remoteDelete","params":{"groupId":"<id>","targetTimestamp":<ts>}}`
   to `/api/v1/rpc` (only the bot's own messages can be deleted).
4. Stop the listener, check the ledger queue is empty, `kubectl -n hermes scale deploy/hermes --replicas=1`.

To see which group member is unreachable without posting anything: `sendTyping` with `"stop": true` to the group
returns per-recipient results (`UNREGISTERED_FAILURE` + `recipientAddress.uuid`).

Per-chat tone without a new bot: `signal.channel_prompts` in config.yaml (key `group:<groupId>`) — **only with the local patch**: upstream's Signal adapter never passes it on (corrected 2026-09-24; earlier notes said it worked). A differently
*named* bot needs its own Signal number + Hermes profile (`hermes profile create <name>`).

## Access & safety model
| Channel | Who | Tools |
|---|---|---|
| CLI (`hermes chat` via `kubectl exec` into deploy/hermes) | you | **full** (terminal, files, code, web, …) |
| Signal DM | members of the owner's groups (auto-synced) + paired users; others get a pairing code | **chat-only** |
| Signal groups where the owner is admin (e.g. "Disney Gang 2025", "Disney Group 2026") | **every member**, only when Mickey is addressed | **chat-only** |

**Chat-only** = `web` (DuckDuckGo search), `vision` (images sent to him), `tts` (voice notes), `memory`, `clarify`,
`todo`, `skills` (docs only). Disabled on Signal: `terminal file code_execution cronjob delegation computer_use
connections image_gen session_search browser`:
```bash
hermes tools disable --platform signal terminal file code_execution cronjob delegation computer_use connections image_gen session_search
hermes tools list --platform signal
```
Why (decided on node1, where `ubuntu` had kubectl admin and passwordless sudo; in k3s Mickey's `local` terminal backend
is the gateway container: no service-account token, read-only rootfs, but it still holds every profile's `.env`
keys on the state volume). Hermes' approval gate only
pauses *dangerous-pattern* commands (`rm -rf` …); plain reads (`cat ~/.hermes/.env`, `kubectl get secret`) are not
gated, so any of 22 group members could have talked Mickey into leaking keys. `session_search` is off because it can
surface CLI sessions (and their command output). Personas ("mind the broom") are not a security boundary.

**Group wake-up** (`SIGNAL_REQUIRE_MENTION=true` + name patterns): Mickey only sees a group message when it @-mentions
him or **addresses** him by name — starts with "Mickey," / "Hey Mickey what…" / "mickey can you…", contains
"Sorcerer Mickey", ends with ", Mickey?", or is just a greeting/thanks + his name ("good morning mickey"). Ordinary Disney talk ("meet Mickey at Toontown", "Mickey pretzels") is
ignored and never leaves the cluster. Patterns (tested 15/15) are in `config.yaml`:
```yaml
signal:
  mention_patterns:
    - '^\W*(?:(?:hey|hi|hello|ok|okay|yo|so)\W+)?(?:sorcerer\s+)?mick(?:e)?y\s*[,:!?]'
    - '^\W*(?:(?:hey|hi|hello|ok|okay|yo|so)\W+)?(?:sorcerer\s+)?mick(?:e)?y\s+(?:what|when|where|who|why|how|can|could|would|will|do|does|is|are|please|pls|tell|find|remind|check|help|look)\b'
    - '\bsorcerer\s+mick(?:e)?y\b'
    - ',\s*(?:sorcerer\s+)?mick(?:e)?y\s*[?!.]*\s*$'
    # whole message = greeting/thanks + name ("good morning mickey", "thanks mickey", "gm Mickey 🌞") — added 2026-09-24
    - '^\W*(?:good\s+(?:morning|afternoon|evening|night|day)|morning|afternoon|evening|night|nite|gm|gn|hi|hiya|hello|hey|howdy|yo|thanks|thank\s+you|thx|ty|cheers|bye|goodbye|see\s+ya|welcome|welcome\s+back)\W+(?:sorcerer\s+)?mick(?:e)?y\W*$'
```
A "silent listener" (see every message, reply only when useful via Hermes' `[SILENT]` marker) was considered and
declined: every group message would become a Sonnet call and all 22 people's messages would go to Anthropic/Honcho.

**Data flow:** addressed messages + replies → Anthropic (Sonnet 5.5) and Honcho (stored; conclusions extracted by the
local Mac coder; memory questions on Sonnet every 3 turns). Tell the group Mickey is an AI with memory.

## Who can talk to him, and who's in charge (updated 2026-09-24)
- **Groups — rule: Mickey takes part in every Signal group where the owner is a group admin.** The owner vouches by
  being admin; invitations from anyone else are ignored. [`bin/signal-allowlist-sync.py`](bin/signal-allowlist-sync.py)
  (CronJob `hermes-allowlist-sync`, **every 10 min**, owner UUID from Secret `hermes-timers`) maintains, for those groups:
  `SIGNAL_GROUP_ALLOWED_USERS` (.env), and a **managed block** in `config.yaml` (between `# BEGIN/END managed-groups`)
  with `signal.group_allowed_chats` (`group:<id>` — every member may talk to him) and a per-group discretion
  `channel_prompts` entry. Restarts the gateway (`patch deploy/hermes`) only on change and only when nothing is queued for delivery.
  - Why the chat-scoped grant: allowing a group only lets its messages in; Hermes then authorizes each **sender**,
    so members were "Unauthorized". Avoid `group_policy: open` (needs the allow-all flag, which would open DMs too).
- **DMs:** `SIGNAL_ALLOWED_USERS` = members of those groups as **UUID and phone number** (senders arrive as either;
  Hermes matches only the primary id). Everyone else gets a pairing code (`hermes pairing approve signal <code>`).
- **Slash-command admin = owner only** (`signal.allow_admin_from` / `group_allow_admin_from`). Without these Hermes
  disables gating and **every allowed user is admin** — anyone could send `/update` (wipes the local patches),
  `/restart`, `/model`, `/personality`, `/rollback`, `/yolo`… Non-admins keep `/help`, `/whoami`; DMs also `/new`, `/stop`.
  (`/tools`, `/toolsets`, `/config`, `/cron`, `/skills` are CLI-only — chat can't re-enable tools.)
- **Self-repair channel:** on Signal Mickey is chat-only and can't edit himself — by design (20+ people, forwarded
  messages and pasted content can steer him). Admin work goes through the **terminal**:
  `kubectl -n hermes exec -it deploy/hermes -c gateway -- hermes chat` (full tools: he can edit his config, restart),
  e.g. over SSH to a node from a phone SSH app over netbird. From Signal the owner has `/restart`, `/new`, `/status`,
  `/usage`, `/model`. **Never `/update`**: upgrades are image builds (the local patches are applied at build time).

## Cost watch (added 2026-09-24)
[`bin/dm-cost-alert.py`](bin/dm-cost-alert.py) via CronJob `hermes-dm-cost-alert` (hourly): sums Hermes' own
per-session estimates for **Signal DMs** (`state.db` → `sessions.chat_type='dm'` + `session_model_usage`) and
Signal-DMs the owner from Mickey's number when DM spend passes **$5/day** or **$30/30 days** (`DM_DAY_USD`,
`DM_30D_USD` in the CronJob env; each alert at most once a day). First day's numbers: owner's long DM session ≈ **10¢/reply**
(big context re-read every turn), group replies ≈ **2.7¢/reply**. Long DM conversations are the cost driver — `/new`
starts a fresh session.

## Persona reinforcement (added 2026-09-24)
- `SOUL.md`: stronger voice (classic exclamations, magic metaphors, "clearly in character" but short answers stay
  short), **example exchanges** (voice anchors — no hard-coded facts in them), and a **Discretion** section: use
  private knowledge to help, never quote/attribute/confirm it; "that's their story to tell"; never discuss setup.
- Lore skill [`skills/sorcerer-mickey/SKILL.md`](skills/sorcerer-mickey/SKILL.md) → `~/.hermes/skills/personal/`:
  Fantasia/Dukas/Goethe, Yen Sid, the broom story, Fantasmic! (Disneyland Rivers of America / Hollywood Studios),
  in-character guidance — and "never answer times/dates from this file; look them up".
- Group reminder (`signal.channel_prompts`, needs the patch): discretion + short, warm, no narration — injected every
  turn in that chat only. Discretion is prompt-level behaviour, not access control: don't tell Mickey anything that
  would really hurt if repeated.

## Backup of Mickey's Signal account (added 2026-09-24; k3s since 2026-10-11)
The signal-cli data dir holds the bot's **identity keys** — losing it means re-registering the number (everyone sees
"safety number changed"); leaking it lets someone send as Mickey. So the backup is consistent, encrypted and replicated:
| Step | What |
|---|---|
| 03:10 UTC in k8s | CronJob `hermes/signal-cli-backup` ([`k8s/timers.yaml`](k8s/timers.yaml), signal-cli image, co-located with the signal-cli pod for its RWO volume): SQLite online `.backup` of `account.db` (WAL) + integrity check + the account JSON → tar → **age**-encrypted to the public key (`age_recipient` in Secret `hermes-timers`) → Longhorn PVC `hermes/signal-cli-backups` (replicated). Avatars skipped (re-download). |
| Key | age identity **only** in secret `hermes/signal-cli-backup-key` (`identity.txt`, `recipient`). Keep a second copy in a password manager. |
| Retired | node1's `signal-cli-backup.timer` → `/var/backups/signal-cli` and the off-node copy CronJob `signal-cli-backup-offnode` ([`k8s/signal-cli-backup.yaml`](k8s/signal-cli-backup.yaml), suspended; kept for rollback) |

Verified 2026-09-24 (node1 version): first archive 1.05 MB; test-decrypt with the secret's key → account
`registered: true`, identity key present, `account.db` integrity ok (19 tables). Verified 2026-10-11: the k8s CronJob,
run by hand, wrote an encrypted backup onto the replicated PVC.

Restore (k3s, outline): scale `deploy/hermes` and `deploy/signal-cli` to 0; in a temporary pod mounting PVCs
`signal-cli-backups` and `signal-cli-data`, `age -d -i <identity.txt from signal-cli-backup-key> signal-cli-<ts>.tar.gz.age
| tar -C <signal-cli-data mount> -xzf -` (restores `data/`), fix ownership to uid 1000, delete the pod, scale signal-cli
then hermes back to 1. Never write the identity to a node's disk. The account must not have been re-registered since
the backup (that would invalidate the restored keys). The node1-era restore is under Pre-k3s below.

## Local patches (applied at image build)
[`patches/signal-local.patch`](patches/signal-local.patch) (copied into [`image/patches/`](image/); the image build fails if a hunk
stops applying) started with three changes to `gateway/platforms/signal.py` (it now also carries the Haiku 5.5
defaults, the Signal group observer and the API-server profile model routes, see below):
1. **Name trigger:** upstream's Signal adapter ignores `mention_patterns` (only WhatsApp/BlueBubbles implement it);
   the patch adds it (~10 lines, reusing `compile_mention_patterns`).
2. **Group duplicate fix:** upstream `_validate_send_result` failed the whole send if **any** recipient result wasn't
   `SUCCESS`. One group member with a deleted Signal account (`UNREGISTERED_FAILURE`) made every group reply "fail",
   and the delivery ledger re-sent it to everyone as "Recovered reply … may be a duplicate" (4 posts on 2026-09-24).
   Now: success if at least one recipient accepted it; per-recipient failures are logged (with the recipient's UUID
   prefix). DMs unchanged.
3. **Per-chat prompts:** passes `signal.channel_prompts` into each message (`MessageEvent.channel_prompt`), which the
   Signal adapter never did.
Without it the group falls back to @-mentions only, and **group replies duplicate again** while any member is unregistered. Worth upstreaming (both).

## Gotchas found
- **Honcho auth over LAN/netbird:** Hermes treats loopback, RFC1918 **and CGNAT (100.64/10 = netbird)** Honcho URLs as
  "local" and sends a placeholder key — an `HONCHO_API_KEY` in `.env` is ignored. The JWT must be `apiKey` **in
  `honcho.json`**.
- **Context floor:** Hermes refuses to run below 64K context (`MINIMUM_CONTEXT_LENGTH`). On Ollama it sends `num_ctx`
  per request, overriding the daemon default.
- **qwen3.8:27b on Ollama** (first model tried): worked (tool calls OK, 18.5 GB at 64K) but ~22 s/turn, ~90 s cold,
  and Ollama serializes its architecture (4 parallel requests = 4× wall time). Switched to Sonnet 5.
- **Tool prompt:** ~11K tokens of tool schemas per request (24 tools after trimming). Prompt caching keeps it cheap.
- **Web search:** with no provider set, Hermes used Firecrawl's keyless mode → 403. `ddgs` (DuckDuckGo) is free but
  not installed by default. Page *extraction* has no free backend (agent can still `curl` via terminal in the CLI).
- **Browser tools** need Playwright Chromium (skipped at install) → disabled rather than installed (RAM).
- **`hermes doctor` said web/browser were available; live tests showed they weren't** — test tools for real.
- **Mickey can reconfigure himself** when he has tools: over DM (before Signal went chat-only) he edited `.env`,
  ran `hermes update` on request, and asked for `/restart` (he can't restart the process he runs in).
  Avoid editing config from two places at once.
- **Reasoning in chat:** the installer template sets `display.show_reasoning: true`, so every Signal message was
  prefixed with `💭 Reasoning:` (Sonnet's thinking summary). It's the gateway, not the model — telling Mickey "no
  reasoning posts" can't work. Fixed with `hermes config set display.platforms.signal.show_reasoning false` (CLI keeps it).
- **Delivery ledger replays failed replies on startup** (`state='failed'`, `attempts < 3`, < 24 h old). Before restarting
  after a delivery problem, mark stuck rows abandoned (gateway stopped):
  `sqlite3 ~/.hermes/state.db "update delivery_obligations set state='abandoned' where state in ('pending','attempting','failed')"`
  (the image has no `sqlite3` CLI: use `/opt/hermes/.venv/bin/python -c 'import sqlite3; …'` in a pod mounting `hermes-state`)
- Most group members are UUID-only to the bot (Signal number privacy), and Signal's registration check
  (`getUserStatus`) only accepts phone numbers, so an unregistered member can't be looked up directly. signal-cli's
  `Failed to retrieve profile … 404` only means the bot lacks that person's profile key — **not** that they're
  unregistered. The patched adapter logs the failing recipient's UUID prefix instead:
  `kubectl -n hermes logs deploy/hermes -c gateway | grep "partial delivery"`. Plausible cause when every name looks fine: a member
  deleted/re-created their Signal account, so the group still holds the old account while the phone shows the
  contact name.
- `hermes` CLI keeps printing "a previous `hermes update` … did not restart running gateways" — cosmetic after a
  gateway restart.
- Hermes warns SQLite 3.45.1 has the WAL-reset bug; it already falls back to `journal_mode=DELETE`. Harmless.

## Web dashboard (added 2026-09-25; k3s since 2026-10-11)
Container `dashboard` in deploy `hermes` runs `hermes dashboard --host 0.0.0.0 --port 9119 --no-open --skip-build`
(Service `hermes-dashboard:9119`, ClusterIP). NetworkPolicy: reachable **only from the cloudflared namespace**, so the
only way in is https://hermes.geekstyle.net (the old LAN/netbird URLs on node1:9119 are gone).
- Careful in the UI: the managed-groups block is overwritten by the sync job; re-enabling Signal toolsets re-opens
  terminal/file access to group members; don't update Hermes from the UI (upgrades are image builds).
- Hermes refuses a non-loopback bind without an auth provider.

### Public access + SSO (added 2026-09-27)
- **https://hermes.geekstyle.net** — Cloudflare Tunnel → `http://hermes-dashboard.hermes.svc.cluster.local:9119`
  (Service in ns hermes, no k8s Ingress; was `http://192.168.4.101:9119` on node1 until 2026-10-11).
- Two gates: **Cloudflare Access** (login method = Zitadel, policy = owner's email, 12h session) in front, then the
  dashboard's own login, **"Sign in with Self-hosted"** = Zitadel OIDC (built-in `plugins/dashboard_auth/self_hosted`,
  public client + PKCE). The second login is silent SSO (same Zitadel session).
- `config.yaml`: `dashboard.public_url: https://hermes.geekstyle.net` (redirect = `<public_url>/auth/callback`) and
  `dashboard.oauth.self_hosted.{issuer: https://auth.geekstyle.net, client_id: <zitadel app client id>, scopes}`.
  The Zitadel app lives in project `homelab`, whose role check refuses tokens to anyone without a grant — the dashboard
  plugin has no allowlist of its own, so that project setting is what restricts it.
- **SSO-only since 2026-09-29**: password login removed (with two providers Hermes always shows a picker; with exactly
  one OAuth provider it auto-redirects to SSO). Break-glass if Zitadel/Cloudflare is down: **not adapted to k3s yet**
  — `bin/set-dashboard-password` (in the image at `/opt/geekstyle/bin/`) still calls `systemctl`; it would need to
  write `dashboard.basic_auth` only, followed by `kubectl -n hermes rollout restart deploy/hermes`, plus a
  `kubectl port-forward` to reach the ClusterIP. TODO.
- Binding `0.0.0.0` accepts any Host header, so the Service name works with `public_url` set.

## Second assistant: Luna (profile `luna`, added 2026-10-07)
A separate Hermes **profile** (`~/.hermes/profiles/luna`, own persona/memory/Honcho workspace `luna`) served headless by
the same multiplexed gateway's **OpenAI-compatible API server** (now Service `hermes-api.hermes.svc:8642`; on node1 it
was `192.168.4.101:8642`), `/p/luna/v1`, luna-only key,
with a multi-user **Open WebUI front end at https://luna.geekstyle.net**. Chat-only tools; not on Signal; no dashboard
(the dashboard is an owner console that can reach every profile). Full design, security checks and "adding a person":
[`../luna/README.md`](../luna/README.md).
- Changes to Mickey's side: `~/.hermes/.env` gained `API_SERVER_*` (API server on; bound to 192.168.4.101 on node1,
  `0.0.0.0` in k3s with NetworkPolicy limiting it to the Luna/Cheshire webui pods); default
  profile's `platform_toolsets.api_server` is chat-only. Mickey's Signal setup is unchanged.

## Model picker vs. new Claude models (2026-10-08)

Hermes' model picker is a **static list** in `hermes_cli/models_catalog_static.py`, not Anthropic's live `/v1/models`, so
new models lag. Typing an ID always works (Hermes probes `/v1/models`): `/model claude-sonnet-5-5`.

**Haiku: 5.5 everywhere, not 4.5** (owner's rule). Upstream hard-codes `claude-haiku-4-5-20251001` as the Anthropic
"cheap auxiliary model" (fallback for side tasks such as titles/compression when they don't run on the main model).
The local patch changes it to `claude-haiku-5-5` in `plugins/model-providers/anthropic/__init__.py`
(`default_aux_model`) and `agent/auxiliary_client.py` (legacy table + OAuth fallback), and the picker's Anthropic list
shows `claude-sonnet-5-5` / `claude-haiku-5-5` instead of Haiku 4.5. Verified: an auxiliary call with no model named
resolves to `claude-haiku-5-5`. The Signal group digests also use `claude-haiku-5-5` (`observe_digest_model`).

## GitLab MCP (scm.geekstyle.net) — 2026-10-08

`mcp_servers.gitlab.url: https://scm.geekstyle.net/api/v4/mcp` (was gitlab.com), `auth: oauth`. Hermes registers itself
via GitLab's dynamic client registration ("[Unverified Dynamic Application] Hermes Agent", scope `mcp`) and acts as the
owner's GitLab user. Tools: 27 (issues, MRs, pipelines, job logs, search, …) — CLI/dashboard only; Signal and Luna
toolsets stay chat-only.

- **GitLab CE ships its MCP server disabled**: with a valid token `/api/v4/mcp` returns **404** until the instance
  setting is on: `gitlab-rails runner 'ApplicationSetting.current.update!(mcp_server_enabled: true)'` (done). Settings
  are cached per Puma worker for ~1 min — restart the Hermes gateway only after `/api/v4/mcp` answers 200 consistently,
  otherwise it parks the server as Not Found.
- **Login (one-time, interactive, done on node1 2026-10-08; the tokens moved to k3s with the state):** `hermes mcp login gitlab` on node1 → open the printed URL → Authorize. The redirect
  goes to `http://127.0.0.1:27890/callback` on node1: either `ssh -N -L 27890:127.0.0.1:27890 ubuntu@192.168.4.101`
  first, or paste the failed redirect URL back into the prompt. Tokens: `~/.hermes/mcp-tokens/gitlab*.json` (0600). A re-login in k3s has not been needed or tested yet.
- **Check:** `hermes mcp test gitlab` lists the tools; gateway log shows `MCP: registered 27 tool(s) from 1 server(s)`.

## Mac Studio models in the /model menu (2026-10-08)

Named provider **`mac-studio`** ("Mac Studio (Ollama)") in `~/.hermes/config.yaml` → `providers:` —
`base_url: http://mac-studio.hermes.svc.cluster.local:11434/v1` (the in-cluster relay since 2026-10-11; was the Mac's netbird IP), `transport: chat_completions`, `default_model: qwen3.8:27b`,
`context_length: 65536`. It only adds a menu entry; Mickey's default stays `anthropic` / `claude-sonnet-5-5`
(context 200K). The picker discovers the Ollama model list live. Use: `/model` → Mac Studio (Ollama), or
`hermes chat --provider mac-studio`. Tested: qwen3.8:27b answers (cold ~70 s incl. model load, warm ~30 s).

(Briefly the default model was switched to qwen with `hermes config set model.*` — that *replaces* the main model;
use a `providers:` entry to just add a choice.)

## Who is who (2026-10-08)

| Assistant | Profile | Used by | Front end |
|---|---|---|---|
| Sorcerer Mickey | `default` | several people — Signal group | Signal (chat-only); CLI/dashboard = admin |
| Cheshire | `cheshire` | owner, 1:1 | https://cheshire.geekstyle.net (`../cheshire/`) |
| Luna | `luna` | Anna (owner temporarily, while she settles in) | https://luna.geekstyle.net (`../luna/`) |

The dashboard at hermes.geekstyle.net is the admin console only (Access session 12h). Each profile has its own Honcho
workspace (hermes / cheshire / luna) with a workspace-scoped token, so their long-term memories never mix.

## Signal groups: Mickey reads everything, replies only when addressed (2026-10-08)

Local patch (`patches/signal-local.patch`, applied at image build; it now also carries the Haiku 5.5 defaults above), Signal analogue
of Hermes' Telegram-only `observe_unmentioned_group_messages`, but designed to keep **per-person sessions and
per-person Honcho memory** (`group_sessions_per_user: true`):

- `gateway/platforms/signal.py` `_GroupObserver`: every message in an allowed group (addressed or not, plus Mickey's
  own replies) goes into a bounded per-group buffer — last `observe_max_messages` within `observe_max_age_hours` — persisted as `~/.hermes/signal-observed/<sha256(group)>.json` (0600, survives restarts, self-pruning).
- Unaddressed messages are **not dispatched** (no model call, no cost). When someone addresses Mickey (name pattern,
  @mention), the recent buffer is appended to **that turn's channel prompt** as a delimited, context-only block —
  ephemeral: not stored in the sender's transcript or sent to Honcho as theirs, so nobody is attributed someone
  else's words. Quoted text is sanitized (`===` neutralized so it can't forge the block markers; 500 chars per message,
  8 KB per block) and the block says plainly that instructions inside it are not requests.
- `gateway/config_loader.py`: lets `observe_unmentioned_group_messages`, `observe_self_name`, `observe_max_messages`,
  `observe_max_age_hours` through for Signal.
- Config (`~/.hermes/config.yaml` → `signal:`): `observe_unmentioned_group_messages: true`,
  `observe_self_name: "Sorcerer Mickey"`, `observe_max_messages: 100`, `observe_max_age_hours: 36` + digest keys below.
- Tested with simulated envelopes: two unaddressed messages → 0 dispatches; "Mickey, what do you think?" → 1 dispatch,
  sender's own user id, both earlier messages in the context block; forged end-markers neutralized.
- Turn off: set `observe_unmentioned_group_messages: false` (or delete `~/.hermes/signal-observed/`) and restart.
- **Window (raised same day):** 100 messages / 36 h, up to 12 KB shown per addressed turn.
- **Group digests (same day):** a background loop (every 2 min) summarizes each group's not-yet-digested messages
  once the chat has been quiet for 30 min and at least 6 human messages piled up — or immediately when the backlog
  reaches 80 % of the window, so nothing rolls out unseen. Model: **`claude-haiku-5-5`** via Hermes' auxiliary client
  (`async_call_llm`, task `signal_group_digest`, same Anthropic credentials) — independent of Mickey's main model
  (Sonnet 5.5). Small talk → the model answers `NOTHING` and no digest is stored. Digests (2-8 bullets, ≤120 words,
  sensitive personal details left out) are kept **30 days** in the same per-group file and shown (up to 4 KB, oldest
  first) above the recent messages on addressed turns. Previous digest is passed along for continuity.
  Config keys: `observe_digest`, `observe_digest_provider`, `observe_digest_model`, `observe_digest_quiet_minutes`,
  `observe_digest_min_messages`, `observe_digest_retention_days`, `observe_digest_block_chars`,
  `observe_max_block_chars`. Tested with a real Haiku call: a planning exchange → 3-bullet digest; greetings → nothing.
- **Multiplexed-gateway gotcha (fixed same day):** the digest loop is a background task with no per-turn secret scope,
  so `async_call_llm` raised `UnscopedSecretError` ("could not read this profile's ANTHROPIC_TOKEN") every 2 min. Fix:
  wrap the call in `set_secret_scope(build_profile_secret_scope(<profile home>))` like `cron/scheduler.py` does (home
  captured when the Signal adapter starts). First digests then landed for both waiting groups.
- **Privacy:** with digests, Mickey keeps a 30-day summary record of each group's conversations (not only messages
  addressed to him). Groups should know. Off: `observe_digest: false`; erase: delete `~/.hermes/signal-observed/`.
- Not done: letting Mickey speak up unprompted when relevant (a model call per message; idea: Haiku relevance gate +
  `[SILENT]` + rate cap).

## S3 storage for Cheshire and Luna (2026-10-08)

`mcp/s3_store.py` — a small stdio MCP server (in the image at `/opt/geekstyle/local-mcp/s3_store.py`; on node1 it was `~/.hermes/local-mcp/`; run with the Hermes venv's
boto3) that each profile launches with **its own scoped SeaweedFS key** (`HERMES_S3_ACCESS_KEY/SECRET_KEY` in the
profile `.env`). Buckets: `mine` = `hermes-<profile>`, `shared` = `hermes-shared` (Cheshire ↔ Luna). SeaweedFS enforces
the scoping server-side (see `../seaweedfs/README.md`); the tool can't name any other bucket anyway.

Tools: `s3_list`, `s3_upload_file` (only files inside the profile's media caches — received/generated images, documents,
audio; anything else e.g. `.env` is refused), `s3_put_text`, `s3_get_text` (≤256 KB), `s3_download` (to
`<profile>/cache/s3-downloads`, so vision etc. can use it), `s3_share_link` (presigned, ≤7 days; reachable at home /
netbird only), `s3_delete`. Enabled in both profiles' `api_server` and `cron` toolsets as `mcp-s3`
(`mcp_servers.s3` in each profile's config). Verified: stdio test of every tool + guards; Cheshire wrote a note to
shared and Luna read it; Luna has no route to Cheshire's bucket.

Note: Luna's own bucket is shared by everyone who uses Luna (currently Anna and the owner) — same caveat as her memory.

## Model picker + repo tool (2026-10-08)
- `gateway.platforms.api_server.direct_model_requests: true` (default profile config — the API server is shared): a bare
  `model` in an OpenAI-style request is honored. Used by cheshire.geekstyle.net's Opus/Sonnet/Haiku picker. The
  `provider::model` prefix is *not* honored on /v1/chat/completions; an explicit `provider` field is.
- `mcp/repo_files.py`: generic stdio MCP for maintaining a fixed set of GitLab repos with project tokens (see
  `../cheshire/README.md`).

## Commits for Cheshire and Luna (2026-10-09)

GitLab 19.3's built-in MCP server has no file/commit tools (only add_branch / create_merge_request / notes / pipelines),
so `mcp/repo_files.py` gained a **bot mode** (`REPO_FILES_BOT`): any repo under the profile's allowed namespaces, named by
full path, reached with the bot's own `api`-scoped PAT (`hermes-repo-files`, 1 year; `CHESHIRE_BOT_API_TOKEN` /
`LUNA_BOT_API_TOKEN` in the profile `.env`). New tools `repo_projects`, `repo_create_project` (PRIVATE only); file tools
take a `branch` (new names are created from the default branch). GitLab's roles + protected default branches are the
boundary; the tool adds namespace allow-lists and never writes CI/build files.

| | allowed namespaces | direct to main | elsewhere |
|---|---|---|---|
| Cheshire (`cheshire-bot`) | `geekstyle/members/cheshire/`, `geekstyle/platform/`, `geekstyle/projects/`, `cheshire/` | own space (Maintainer) | new branch → MR (Developer; `cheshire/docs` main stays protected, so publishing still only via the `pages` shortcut + "yes, publish") |
| Luna (`luna-bot`) | `geekstyle/members/ladyofkrypton/` | Anna's space (Maintainer) | — |

Web chat only (not in cron). Verified: stdio guard tests; Cheshire committed to `cheshire/commit-test` and opened an MR
(closed + branch deleted afterwards); Luna created a private repo in Anna's space and committed (deleted afterwards).

**Regression caught the same day:** enabling `direct_model_requests` made the API server forward each profile's own
virtual model name (`luna`, `cheshire`) to Anthropic as a model id → 404 for every Luna message (~45 min; only test
traffic hit it). Fixed with a local patch in `gateway/platforms/api_server_openai_routes.py`: the virtual id under
`/p/<profile>/` is that profile's name (same rule `/v1/models` uses). Re-verified: Luna's own name → her default model;
Cheshire's picker → Opus / Sonnet / Haiku each correct. Patch carried in `patches/signal-local.patch`.

**Default models:** Mickey `claude-sonnet-5-5`; Cheshire `claude-opus-5-5` (+ picker); Luna `claude-opus-5-5` (2026-10-09).

## k3s migration log (2026-10-11)

Cut over 2026-10-11 ~21:20 UTC. node1's units (`hermes-gateway`, `hermes-dashboard`, `signal-cli`, the three timers)
are **stopped and disabled**; node1's `~/.hermes` and signal-cli data were only read, so `k8s/rollback.sh` still returns
to the pre-cutover state (anything said since lives only in the k3s volumes). Longhorn
`node-down-pod-deletion-policy` set to `delete-both-statefulset-and-deployment-pod` (cluster-wide) so a dead node
fails the pods over.

Current layout: see [k3s deployment](#k3s-deployment-current-since-2026-10-11) at the top.

**Verified before cutover (2026-10-11)** from a pod with the gateway's label on node2: SSH into both sandboxes with
pinned host keys, Luna's key refused by Cheshire's sandbox, no DNS in sandboxes, Mac relay answers from node2; Hermes
tools from the image against `sbx-luna`: terminal, write/read_file, execute_code (openpyxl), sync-back canary unchanged;
render_docs → service: Mermaid PNG/SVG, Markdown PDF, HTML PNG; gateway API + dashboard boot as uid 1000 on ro rootfs;
CI smoke jobs green for all four images. Config rewrite tested on a copy (idempotent, YAML valid).

**Cutover log / verified after (2026-10-11).**
- Copy Job: first runs failed on root-owned files (`.env.bak-*`, `config.yaml.bak-sync` on node1; volume roots and the
  kubelet-created `gnupg` subPath dirs) → the Job now runs as root, archives top-level entries (not `.`), skips those
  backups and `chown -R 1000:1000`s the volumes. Failure detection waits for complete **or** failed (the first run
  sat out the 600 s timeout). ~25 min total Hermes downtime, most of it the failed attempts.
- Luna replied through the k3s gateway and wrote/read a file in `sbx-luna` over SSH; Cheshire's GnuPG secret key is
  present in `sbx-cheshire`; Signal adapter connected (SSE) to the signal-cli Service; `hermes.geekstyle.net` →
  Access → dashboard (302 to OIDC) from the cloudflared namespace; `signal-cli-backup` CronJob run by hand → encrypted
  backup on the replicated PVC. The node1 ipBlocks were removed from `hermes-sandboxes`.
- Manifests now say `replicas: 1` (re-applying the old `replicas: 0` files after cutover scaled Hermes down once —
  2 min outage). `cutover.sh` preflight therefore refuses to run again unless everything was rolled back to 0.
- **k3-node3 does not enforce NetworkPolicies**: kube-router's per-pod chains exist there but count 0 packets; a test
  pod on node4 reached render, the Mac relay, signal-cli RPC and the sandbox SSH ports on node3, while the same test
  against the gateway on node2 was refused. signal-cli (unauthenticated RPC) is therefore **required off node3**
  for now (it runs on node2, verified refused from other pods); the sandboxes (SSH key auth + host-key pinning), render
  and relay remain on node3. Root cause found 2026-10-12: the NetBird routing-peer fwmark lets pod traffic bypass
  kube-router (node3 **and** node4, both NetBird routing peers); fix planned in `../netbird/PLAN-opnsense-router.md`.
- **Post-cutover regression, fixed 22:48 UTC:** on first boot v0.21.6's package manager built its own venv under
  `$HERMES_HOME/installs/<key>/environments/` (4 generations, 6.5 GB, extras = `anthropic` only) and relaunched the
  gateway into it — no `mcp` SDK, no `honcho-ai`, so **every MCP server (GitLab, repos, s3, render, luna-publish) and
  Honcho memory silently failed for all profiles** (Cheshire noticed: no git tools). Selection rule
  (`pm/environments.py`): `installs/<key>/facts.json` present → that env, else the image's `/opt/hermes/.venv`.
  Fix: `installs/` moved to `installs.disabled-20261011` and replaced by a **root-owned 0755 dir** (uid 1000 can't build
  a new one); `cutover.sh`'s copy Job now does the same. Verified: gateway maps `/opt/hermes/.venv`, MCP 42/60/63 tools
  registered for default/cheshire/luna, Cheshire listed GitLab projects, Honcho activates. TODO: image smoke test should
  exercise an MCP server + Honcho import inside `gateway run`, and delete `installs.disabled-*` once stable.
- Gateway warnings worth knowing: `TERMINAL_CWD does not exist: /workspace` (harmless — the cwd is in the sandbox);
  "API server network-accessible AND terminal backend local" refers to the default profile (Mickey), whose API is
  reachable only from the Luna/Cheshire webui pods by NetworkPolicy (node2) and needs its own key.

## Diagrams and documents for Cheshire and Luna (2026-10-09)

Survey of what Hermes already ships (v0.21.5), and what the two web assistants can actually use:

| Need | Built in | Usable by Cheshire/Luna? |
|---|---|---|
| Mermaid | Open WebUI (0.11.4 then; 0.12.0 now) renders ```mermaid in chat; GitLab renders it in Markdown | yes, prompt guidance only (SOUL) |
| SVG/HTML diagrams | skills `architecture-diagram`, `concept-diagrams`, optional `archify` | as chat code; saving needs `write_file` (denied) |
| PDF / DOCX / PPTX | skills `pdf`, `docx`, optional `pptx-author` (python scripts) | no — need the `terminal` tool |
| Excalidraw / tldraw | optional skills | not installed; need file tools |
| Returning files | API server inlines **images only** (`MEDIA:<path>` → data URL, ≤5 MB); no PDF/DOCX delivery to Open WebUI | via S3 links / repos |

Terminal/file stayed **denied** at the time: the terminal backend was `local`, i.e. node1's host (every token, kube
admin). *Since then:* Cheshire (2026-10-09) and Luna (2026-10-11) got Docker sandboxes on node1, and since the k3s
cutover their terminal/file/code tools run in the SSH sandbox pods `sbx-cheshire` / `sbx-luna` (`sandbox/ssh/`).

**What was added instead — `mcp/render_docs.py`** (stdio MCP, toolset `mcp-render`, in both profiles' `api_server`
and `cron` lists):

| Tool | In → out |
|---|---|
| `render_mermaid` | Mermaid → svg / png / pdf (themes, background, PNG scale) |
| `render_markdown` | Markdown (+ ```mermaid blocks drawn) → PDF (US Letter) / standalone HTML |
| `render_html` | HTML page or bare `<svg>` → pdf / png (sized to content, or Letter/A4) / svg |

- **Since 2026-10-11** rendering goes to the `hermes-render` Service (`RENDER_URL=http://hermes-render.hermes.svc.cluster.local:8080`,
  [`k8s/render.yaml`](k8s/render.yaml): no egress, only the gateway may connect); the MCP server is in the image at
  `/opt/geekstyle/local-mcp/render_docs.py`. The node1 setup as built on 2026-10-09:
- Rendering: headless Chromium in `zenika/alpine-chrome@sha256:eb3378c1…` (pinned digest, arm64) via `docker run`
  `--network none --read-only --cap-drop ALL --security-opt no-new-privileges`, 1.5 GB / 2 CPU / 512 pids, running as
  the gateway's uid, only the job dir mounted (+ vendor dir read-only). Untrusted markup can run scripts there but
  reach nothing (verified: `fetch()` fails).
- Mermaid **11.17.2** vendored at `~/.hermes/local-mcp/render/vendor/` (sha512 checked against npm integrity) — no CDN.
  `securityLevel: 'strict'`, `htmlLabels: false` so SVG output is pure SVG (valid XML, no foreignObject).
- Headless gotcha (same as the ai-infra slides CI): under `--virtual-time-budget` Chrome doesn't reliably produce
  animation frames, so pages get a `requestAnimationFrame`→`setTimeout` shim.
- Output: `profiles/<p>/cache/renders/` (kept 30 days) — inside the s3 and repos upload roots and the MEDIA delivery
  allowlist, so the assistant can show a PNG inline, `s3_upload_file` + `s3_share_link`, or `repo_upload_file`.
  One render at a time per profile (flock), 90 s timeout, 1 MB input / 50 MB output caps, PDF page count reported.
- Install: `~/.hermes/local-mcp/render_docs.py` (+ `render/vendor/`), `mcp_servers.render` in both profile configs
  (env: `RENDER_OUT_DIR`, `RENDER_WORK_DIR`, `RENDER_VENDOR_DIR`, `RENDER_IMAGE`); `docker pull` the image once.
- SOUL: both got a "Diagrams and documents" section (Mermaid in chat; which render tool for what; how to deliver).
  Luna's public `publish_document` pages are text-only and the Pages CSP blocks scripts, so Mermaid isn't drawn there.
- Verified through the real API: Cheshire drew a Mermaid PNG and it came back inline; Luna produced a Markdown PDF
  with a pie chart.

## Pre-k3s (node1, rollback only)

Everything below describes the host install on k3-node1 (2026-09-24 → 2026-10-11). node1's units (`hermes-gateway`,
`hermes-dashboard`, `signal-cli`, `hermes-allowlist-sync.timer`, `hermes-dm-cost-alert.timer`,
`signal-cli-backup.timer`) are **stopped and disabled**; their files in [`systemd/`](systemd/) and node1's `~/.hermes` are
kept only so [`k8s/rollback.sh`](k8s/rollback.sh) can return to that state.

### At a glance (node1, until 2026-10-11)
| Part | Value |
|---|---|
| Hermes | v0.21.4, `~/.hermes/hermes-agent` (git checkout, user install as `ubuntu`), command `~/.local/bin/hermes` |
| Persona | `~/.hermes/SOUL.md` (copy: [`SOUL.md`](SOUL.md)); original saved as `SOUL.md.orig` |
| Model | `claude-sonnet-5-5` (since 2026-10-08; was `claude-sonnet-5`) (provider `anthropic`), working context capped at 200K (`model.context_length`) |
| Memory | Honcho workspace `hermes` via `http://127.0.0.1:8800` (the Honcho netbird relay's listener on node1). Peers: `mdella` (owner), `sorcerer-mickey` (the bot), `signal_<uuid>` (other Signal users) |
| Signal | dedicated number, `signal-cli` 0.14.8 daemon on `127.0.0.1:8093` → `hermes-gateway` |
| Services | `signal-cli.service`, `hermes-gateway.service` (both system units, run as `ubuntu`, enabled at boot) |
| Footprint on node1 | gateway ~210 MB, signal-cli ~290 MB RSS |

### Where things were (node1)
| File | What |
|---|---|
| `~/.hermes/config.yaml` | model, memory provider, web search backend, per-platform toolsets, `signal.mention_patterns` |
| `~/.hermes/.env` (0600) | `ANTHROPIC_API_KEY`, `SIGNAL_HTTP_URL`, `SIGNAL_ACCOUNT`, `SIGNAL_REQUIRE_MENTION=true`, `SIGNAL_GROUP_ALLOWED_USERS` |
| `~/.hermes/honcho.json` (0600) | `baseUrl`, `apiKey` (workspace-scoped Honcho JWT), `workspace`, `peerName`, `aiPeer`, `dialecticCadence: 3`, `userPeerAliases`, `runtimePeerPrefix: signal_` |
| `~/.hermes/SOUL.md` | Sorcerer Mickey persona |
| `~/.hermes/local-patches/signal-local.patch` | local patch (copy: [`patches/`](patches/)) |
| `~/.hermes/local-patches/ssh-no-sync-back.patch` | 2026-10-11: SSH backend never copies sandbox changes back onto the host (see [`sandbox/ssh/`](sandbox/ssh/)); re-apply after `hermes update` |
| `~/.local/share/signal-cli/` | the bot's Signal account keys — **back this up**; losing it means re-registering the number |
| `/opt/signal-cli-0.14.8`, `/opt/signal-cli/native/libsignal_jni.so`, `/usr/local/bin/signal-cli` | signal-cli + ARM64 native lib + wrapper |

### Install (what was done)
```bash
# 1. Hermes — non-interactive user install, pinned (later updated to 88dee3e866 via `hermes update`)
curl -fsSL https://hermes-agent.nousresearch.com/install.sh -o install.sh
bash install.sh --skip-setup --non-interactive --skip-browser --skip-computer-use --commit <full-40-char-sha>
#    (--commit needs the FULL sha; apt steps for ripgrep/ffmpeg ran with sudo — needrestart deferred all restarts)

# 2. Extras the base install lacks (into Hermes' own venv; re-check after `hermes update`)
VIRTUAL_ENV=~/.hermes/hermes-agent/venv ~/.hermes/bin/uv pip install honcho-ai==2.2.0 ddgs

# 3. Model + memory + web
hermes config set model.provider anthropic
hermes config set model.default claude-sonnet-5-5
hermes config set model.context_length 200000
hermes config set memory.provider honcho
hermes config set web.search_backend ddgs
#    ANTHROPIC_API_KEY=... appended to ~/.hermes/.env (same key as the honcho-secrets Secret)

# 4. Honcho token scoped to the "hermes" workspace, written to ~/.hermes/honcho.json as "apiKey"
kubectl exec -n honcho deploy/honcho-api -c api -- /app/.venv/bin/python scripts/generate_jwt.py --workspace hermes --print-only
```

#### signal-cli on ARM64
```bash
sudo apt-get install -y openjdk-25-jre-headless          # 0.14.8 needs Java 25 (class file 69), not 21
curl -LO https://github.com/AsamK/signal-cli/releases/download/v0.14.8/signal-cli-0.14.8.tar.gz
sudo tar xzf signal-cli-0.14.8.tar.gz -C /opt && sudo ln -sfn /opt/signal-cli-0.14.8 /opt/signal-cli
# the bundled libsignal-client-0.102.1.jar has NO linux-aarch64 lib → exact-version build from exquo/signal-libs-build:
curl -LO https://github.com/exquo/signal-libs-build/releases/download/libsignal_v0.102.1/libsignal_jni.so-v0.102.1-aarch64-unknown-linux-gnu.tar.gz
sudo mkdir -p /opt/signal-cli/native && sudo tar xzf libsignal_jni.so-*.tar.gz -C /opt/signal-cli/native
# /usr/local/bin/signal-cli wrapper adds -Djava.library.path=/opt/signal-cli/native (see systemd/)
```
Upgrading signal-cli: check which `libsignal-client-X.jar` it bundles and fetch the **same** version's ARM64 lib.

#### Registering the bot's number (needs a human)
1. Solve https://signalcaptchas.org/registration/generate.html; **right-click** "Open Signal" → *Copy link*
   (Signal Desktop hijacks a left-click). Or catch the `signalcaptcha://…` URL in the browser dev console.
2. `signal-cli -a +1XXXXXXXXXX register --voice --captcha 'signalcaptcha://…'` (SMS never arrived; voice worked)
3. `signal-cli -a +1XXXXXXXXXX verify <code>`
4. `signal-cli -a +1XXXXXXXXXX updateProfile --given-name Sorcerer --family-name Mickey --about "Apprentice wizard of the homelab 🪄"`

The number must **not** be active in the Signal phone app (signal-cli becomes the primary device).
A mistyped first attempt left a local record; `signal-cli -a <number> deleteLocalAccountData` cleans up unverified numbers.

#### Services
- [`systemd/signal-cli.service`](systemd/signal-cli.service): `signal-cli -a <number> daemon --http 127.0.0.1:8093`.
  The HTTP API has **no auth** and controls the account — keep it on loopback.
- `hermes-gateway.service`: generated by
  `sudo HERMES_HOME=/home/ubuntu/.hermes hermes gateway install --system --run-as-user ubuntu --start-now`
  (also enables linger for `ubuntu`).

### node1 dashboard unit (2026-09-25)
`hermes-dashboard.service` ([`systemd/hermes-dashboard.service`](systemd/hermes-dashboard.service)) runs
`hermes dashboard --host 0.0.0.0 --port 9119 --no-open --skip-build` as `ubuntu`, boot-enabled, with **password
login** (Hermes' built-in `basic` provider):
- **URLs:** http://192.168.4.101:9119 (LAN) · http://100.101.160.239:9119 (netbird). User `mdella`.
- **Credentials:** only a **scrypt hash** + a random HMAC signing secret in `config.yaml` (`dashboard.basic_auth`,
  file 0600) — no plaintext password anywhere. Set/change with [`bin/set-dashboard-password`](bin/set-dashboard-password)
  in an interactive SSH terminal (hidden prompt, 12+ chars); it also flips the unit to `0.0.0.0` and restarts it.
  Re-running rotates the secret, signing out existing sessions.
- **Verified:** unauthenticated `/` → 302 `/login`; `/api/config`, `/api/auth/me` → 401 on LAN and netbird; wrong
  password → 401; failed logins are rate-limited. Sessions: 12 h access token auto-refreshed up to 30 days.
- **Caveat:** plain HTTP — on the LAN the password/cookie travel unencrypted (netbird is WireGuard-encrypted). Use a
  unique password. Bound to all interfaces, so pods can reach it too (still password-gated).
- Hermes refuses a non-loopback bind without an auth provider — never switch the host before a password exists.
- Careful in the UI: the managed-groups block is overwritten by the sync job; re-enabling Signal toolsets re-opens
  terminal/file access to group members; updating Hermes from the UI drops the local patch. After a Hermes update that
  changes the web UI, rebuild once (`cd ~/.hermes/hermes-agent/web && npm run build`) because the unit uses `--skip-build`.

### node1 Signal backup + restore
| Step | What |
|---|---|
| 03:10 UTC on node1 | [`bin/signal-cli-backup.sh`](bin/signal-cli-backup.sh) (`signal-cli-backup.timer`): SQLite online `.backup` of `account.db` (WAL) + integrity check + the account JSON → tar → **age**-encrypted to the public key in `/etc/signal-cli-backup.recipient` → `/var/backups/signal-cli/` (root 0700, 14 days). Avatars skipped (re-download). |
| 03:25 UTC in k8s | CronJob `hermes/signal-cli-backup-offnode` ([`k8s/signal-cli-backup.yaml`](k8s/signal-cli-backup.yaml)), pinned to node1, copies new archives (read-only hostPath) to Longhorn PVC `hermes/signal-cli-backups` — replicas on node1/3/4, 30 days. |
| Key | age identity **only** in secret `hermes/signal-cli-backup-key` (`identity.txt`, `recipient`) — node1 holds just the public key. Keep a second copy in a password manager. |

Restore (e.g. onto a rebuilt node1):
```bash
kubectl get secret signal-cli-backup-key -n hermes -o jsonpath='{.data.identity\.txt}' | base64 -d > /tmp/id.txt
# fetch an archive: from /var/backups/signal-cli, or from the PVC via a pod mounting hermes/signal-cli-backups
sudo systemctl stop hermes-gateway signal-cli
age -d -i /tmp/id.txt signal-cli-<ts>.tar.gz.age | tar -C ~/.local/share/signal-cli -xzf -   # restores data/
shred -u /tmp/id.txt
sudo systemctl start signal-cli hermes-gateway
```
The account must not have been re-registered since the backup (that would invalidate the restored keys).

### Update 2026-09-28 (node1): v0.21.4 → v0.21.5 (`0c380abe`)
- `hermes update` kept failing with **"git fetch timed out after 300s"**: the checkout is a *shallow* clone and catching up
  pulled ~325k deltas (5m43s on node1 incl. "Resolving deltas"). Fix: run `git fetch origin main` once **without** a
  timeout, then update (next fetch: ~2 s). Also delete leftover `.git/objects/pack/tmp_pack_*` from aborted fetches.
- Procedure used: `git checkout -- gateway/platforms/signal.py` (patch is saved in `local-patches/`), stop
  `hermes-dashboard`, `hermes update --yes --no-gateway-restart`, `git apply local-patches/signal-local.patch`
  (applied cleanly), check the delivery ledger is empty of pending/failed, `systemctl restart hermes-gateway`.
- ⚠️ **`--no-gateway-restart` is not honoured** — the updater drained + restarted the gateway anyway (briefly
  running unpatched) and restarted `hermes-dashboard.service` itself. Re-apply the patch immediately after.
- Upstream now has a generic `resolve_channel_prompt()` in `gateway/platforms/base.py`, but the Signal adapter still
  doesn't call it, so our `channel_prompt` hunk is still needed (and does not double-inject).

## Log
- 2026-09-24 — Hermes installed on node1; persona Sorcerer Mickey; Honcho workspace `hermes`; model qwen3.8:27b on
  Ollama → switched to claude-sonnet-5 (4× faster). Signal via signal-cli (Java 25 + ARM64 libsignal), dedicated
  number registered by voice; DM pairing; Signal made chat-only; group "Disney Gang 2025" allowed with name-trigger
  wake-up (local patch). Hermes updated to 88dee3e866 (by Mickey, on request).
- 2026-09-24 — Group incident: 4 duplicate posts (unregistered member → whole send treated as failed → ledger re-sends)
  and reasoning shown in every message. Gateway stopped, stuck delivery abandoned, send-result patch + Signal
  `show_reasoning: false`, restarted with nothing replayed.

# Hermes Agent — "Sorcerer Mickey" on k3-node1 (CLI + Signal)

[Hermes Agent](https://github.com/NousResearch/hermes-agent) (Nous Research) running on **k3-node1** as
**Sorcerer Mickey**: a personal assistant reachable from the terminal and from **Signal** (DM + one group chat),
thinking with **Claude Sonnet 5.5** and remembering through the self-hosted **Honcho** (`../honcho/`).
Set up 2026-09-24.

> Public repo: phone numbers, the Signal group ID, Signal UUIDs, the Honcho token and the Anthropic key are
> **not** in these notes — they live only in `~/.hermes/` on node1 (placeholders below).

## At a glance
| Part | Value |
|---|---|
| Hermes | v0.21.4, `~/.hermes/hermes-agent` (git checkout, user install as `ubuntu`), command `~/.local/bin/hermes` |
| Persona | `~/.hermes/SOUL.md` (copy: [`SOUL.md`](SOUL.md)); original saved as `SOUL.md.orig` |
| Model | `claude-sonnet-5-5` (since 2026-10-08; was `claude-sonnet-5`) (provider `anthropic`), working context capped at 200K (`model.context_length`) |
| Memory | Honcho workspace `hermes` via `http://127.0.0.1:8800` (the Honcho netbird relay's listener on node1). Peers: `mdella` (owner), `sorcerer-mickey` (the bot), `signal_<uuid>` (other Signal users) |
| Signal | dedicated number, `signal-cli` 0.14.8 daemon on `127.0.0.1:8093` → `hermes-gateway` |
| Services | `signal-cli.service`, `hermes-gateway.service` (both system units, run as `ubuntu`, enabled at boot) |
| Footprint on node1 | gateway ~210 MB, signal-cli ~290 MB RSS |

## Where things are
| File | What |
|---|---|
| `~/.hermes/config.yaml` | model, memory provider, web search backend, per-platform toolsets, `signal.mention_patterns` |
| `~/.hermes/.env` (0600) | `ANTHROPIC_API_KEY`, `SIGNAL_HTTP_URL`, `SIGNAL_ACCOUNT`, `SIGNAL_REQUIRE_MENTION=true`, `SIGNAL_GROUP_ALLOWED_USERS` |
| `~/.hermes/honcho.json` (0600) | `baseUrl`, `apiKey` (workspace-scoped Honcho JWT), `workspace`, `peerName`, `aiPeer`, `dialecticCadence: 3`, `userPeerAliases`, `runtimePeerPrefix: signal_` |
| `~/.hermes/SOUL.md` | Sorcerer Mickey persona |
| `~/.hermes/local-patches/signal-local.patch` | local patch (copy: [`patches/`](patches/)) |
| `~/.local/share/signal-cli/` | the bot's Signal account keys — **back this up**; losing it means re-registering the number |
| `/opt/signal-cli-0.14.8`, `/opt/signal-cli/native/libsignal_jni.so`, `/usr/local/bin/signal-cli` | signal-cli + ARM64 native lib + wrapper |

## Install (what was done)
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

### signal-cli on ARM64
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

### Registering the bot's number (needs a human)
1. Solve https://signalcaptchas.org/registration/generate.html; **right-click** "Open Signal" → *Copy link*
   (Signal Desktop hijacks a left-click). Or catch the `signalcaptcha://…` URL in the browser dev console.
2. `signal-cli -a +1XXXXXXXXXX register --voice --captcha 'signalcaptcha://…'` (SMS never arrived; voice worked)
3. `signal-cli -a +1XXXXXXXXXX verify <code>`
4. `signal-cli -a +1XXXXXXXXXX updateProfile --given-name Sorcerer --family-name Mickey --about "Apprentice wizard of the homelab 🪄"`

The number must **not** be active in the Signal phone app (signal-cli becomes the primary device).
A mistyped first attempt left a local record; `signal-cli -a <number> deleteLocalAccountData` cleans up unverified numbers.

### Services
- [`systemd/signal-cli.service`](systemd/signal-cli.service): `signal-cli -a <number> daemon --http 127.0.0.1:8093`.
  The HTTP API has **no auth** and controls the account — keep it on loopback.
- `hermes-gateway.service`: generated by
  `sudo HERMES_HOME=/home/ubuntu/.hermes hermes gateway install --system --run-as-user ubuntu --start-now`
  (also enables linger for `ubuntu`).

## Access & safety model
| Channel | Who | Tools |
|---|---|---|
| CLI (`hermes chat`) over SSH to node1 | you | **full** (terminal, files, code, web, …) |
| Signal DM | members of the owner's groups (auto-synced) + paired users; others get a pairing code | **chat-only** |
| Signal groups where the owner is admin (e.g. "Disney Gang 2025", "Disney Group 2026") | **every member**, only when Mickey is addressed | **chat-only** |

**Chat-only** = `web` (DuckDuckGo search), `vision` (images sent to him), `tts` (voice notes), `memory`, `clarify`,
`todo`, `skills` (docs only). Disabled on Signal: `terminal file code_execution cronjob delegation computer_use
connections image_gen session_search browser`:
```bash
hermes tools disable --platform signal terminal file code_execution cronjob delegation computer_use connections image_gen session_search
hermes tools list --platform signal
```
Why: node1 is a control-plane node where `ubuntu` has kubectl admin and passwordless sudo. Hermes' approval gate only
pauses *dangerous-pattern* commands (`rm -rf` …); plain reads (`cat ~/.hermes/.env`, `kubectl get secret`) are not
gated, so any of 22 group members could have talked Mickey into leaking keys. `session_search` is off because it can
surface CLI sessions (and their command output). Personas ("mind the broom") are not a security boundary.

**Group wake-up** (`SIGNAL_REQUIRE_MENTION=true` + name patterns): Mickey only sees a group message when it @-mentions
him or **addresses** him by name — starts with "Mickey," / "Hey Mickey what…" / "mickey can you…", contains
"Sorcerer Mickey", ends with ", Mickey?", or is just a greeting/thanks + his name ("good morning mickey"). Ordinary Disney talk ("meet Mickey at Toontown", "Mickey pretzels") is
ignored and never leaves node1. Patterns (tested 15/15) are in `config.yaml`:
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
  (`hermes-allowlist-sync.timer`, **every 10 min**, owner UUID in a drop-in) maintains, for those groups:
  `SIGNAL_GROUP_ALLOWED_USERS` (.env), and a **managed block** in `config.yaml` (between `# BEGIN/END managed-groups`)
  with `signal.group_allowed_chats` (`group:<id>` — every member may talk to him) and a per-group discretion
  `channel_prompts` entry. Restarts the gateway only on change and only when nothing is queued for delivery.
  - Why the chat-scoped grant: allowing a group only lets its messages in; Hermes then authorizes each **sender**,
    so members were "Unauthorized". Avoid `group_policy: open` (needs the allow-all flag, which would open DMs too).
- **DMs:** `SIGNAL_ALLOWED_USERS` = members of those groups as **UUID and phone number** (senders arrive as either;
  Hermes matches only the primary id). Everyone else gets a pairing code (`hermes pairing approve signal <code>`).
- **Slash-command admin = owner only** (`signal.allow_admin_from` / `group_allow_admin_from`). Without these Hermes
  disables gating and **every allowed user is admin** — anyone could send `/update` (wipes the local patches),
  `/restart`, `/model`, `/personality`, `/rollback`, `/yolo`… Non-admins keep `/help`, `/whoami`; DMs also `/new`, `/stop`.
  (`/tools`, `/toolsets`, `/config`, `/cron`, `/skills` are CLI-only — chat can't re-enable tools.)
- **Self-repair channel:** on Signal Mickey is chat-only and can't edit himself — by design (20+ people, forwarded
  messages and pasted content can steer him; node1 has kubectl admin + passwordless sudo). Admin work goes through
  the **terminal**: `ssh ubuntu@node1` → `hermes chat` (full tools: he can edit his config, apply patches, restart),
  e.g. from a phone SSH app over netbird. From Signal the owner has `/restart`, `/new`, `/status`, `/usage`, `/model`.
  **Never `/update` without re-applying `patches/signal-local.patch` afterwards.**

## Cost watch (added 2026-09-24)
[`bin/dm-cost-alert.py`](bin/dm-cost-alert.py) via `hermes-dm-cost-alert.timer` (hourly): sums Hermes' own
per-session estimates for **Signal DMs** (`state.db` → `sessions.chat_type='dm'` + `session_model_usage`) and
Signal-DMs the owner from Mickey's number when DM spend passes **$5/day** or **$30/30 days** (`DM_DAY_USD`,
`DM_30D_USD` in the unit; each alert at most once a day). First day's numbers: owner's long DM session ≈ **10¢/reply**
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

## Backup of Mickey's Signal account (added 2026-09-24)
The signal-cli data dir holds the bot's **identity keys** — losing it means re-registering the number (everyone sees
"safety number changed"); leaking it lets someone send as Mickey. So the backup is consistent, encrypted and off-node:
| Step | What |
|---|---|
| 03:10 UTC on node1 | [`bin/signal-cli-backup.sh`](bin/signal-cli-backup.sh) (`signal-cli-backup.timer`): SQLite online `.backup` of `account.db` (WAL) + integrity check + the account JSON → tar → **age**-encrypted to the public key in `/etc/signal-cli-backup.recipient` → `/var/backups/signal-cli/` (root 0700, 14 days). Avatars skipped (re-download). |
| 03:25 UTC in k8s | CronJob `hermes/signal-cli-backup-offnode` ([`k8s/signal-cli-backup.yaml`](k8s/signal-cli-backup.yaml)), pinned to node1, copies new archives (read-only hostPath) to Longhorn PVC `hermes/signal-cli-backups` — replicas on node1/3/4, 30 days. |
| Key | age identity **only** in secret `hermes/signal-cli-backup-key` (`identity.txt`, `recipient`) — node1 holds just the public key. Keep a second copy in a password manager. |

Verified 2026-09-24: first archive 1.05 MB; test-decrypt with the secret's key → account `registered: true`, identity key
present, `account.db` integrity ok (19 tables); off-node copy landed on the PVC.

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

## Local patch (re-apply after `hermes update`)
[`patches/signal-local.patch`](patches/signal-local.patch) makes three changes to `gateway/platforms/signal.py`:
1. **Name trigger:** upstream's Signal adapter ignores `mention_patterns` (only WhatsApp/BlueBubbles implement it);
   the patch adds it (~10 lines, reusing `compile_mention_patterns`).
2. **Group duplicate fix:** upstream `_validate_send_result` failed the whole send if **any** recipient result wasn't
   `SUCCESS`. One group member with a deleted Signal account (`UNREGISTERED_FAILURE`) made every group reply "fail",
   and the delivery ledger re-sent it to everyone as "Recovered reply … may be a duplicate" (4 posts on 2026-09-24).
   Now: success if at least one recipient accepted it; per-recipient failures are logged (with the recipient's UUID
   prefix). DMs unchanged.
3. **Per-chat prompts:** passes `signal.channel_prompts` into each message (`MessageEvent.channel_prompt`), which the
   Signal adapter never did.
```bash
cd ~/.hermes/hermes-agent && git apply ~/.hermes/local-patches/signal-local.patch && sudo systemctl restart hermes-gateway
```
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
- **Browser tools** need Playwright Chromium (skipped at install) → disabled rather than installed (RAM on node1).
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
- Most group members are UUID-only to the bot (Signal number privacy), and Signal's registration check
  (`getUserStatus`) only accepts phone numbers, so an unregistered member can't be looked up directly. signal-cli's
  `Failed to retrieve profile … 404` only means the bot lacks that person's profile key — **not** that they're
  unregistered. The patched adapter logs the failing recipient's UUID prefix instead:
  `journalctl -u hermes-gateway | grep "partial delivery"`. Plausible cause when every name looks fine: a member
  deleted/re-created their Signal account, so the group still holds the old account while the phone shows the
  contact name.
- `hermes` CLI keeps printing "a previous `hermes update` … did not restart running gateways" — cosmetic after a
  gateway restart.
- Hermes warns SQLite 3.45.1 has the WAL-reset bug; it already falls back to `journal_mode=DELETE`. Harmless.

## Web dashboard (added 2026-09-25)
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

### Public access + SSO (added 2026-09-27)
- **https://hermes.geekstyle.net** — Cloudflare Tunnel → `http://192.168.4.101:9119` (host service, no k8s Ingress).
- Two gates: **Cloudflare Access** (login method = Zitadel, policy = owner's email) in front, then the dashboard's own
  login, which now offers **"Sign in with Self-hosted"** = Zitadel OIDC (built-in `plugins/dashboard_auth/self_hosted`,
  public client + PKCE). The second login is silent SSO (same Zitadel session).
- `config.yaml`: `dashboard.public_url: https://hermes.geekstyle.net` (redirect = `<public_url>/auth/callback`) and
  `dashboard.oauth.self_hosted.{issuer: https://auth.geekstyle.net, client_id: <zitadel app client id>, scopes}`.
  The Zitadel app lives in project `homelab`, whose role check refuses tokens to anyone without a grant — the dashboard
  plugin has no allowlist of its own, so that project setting is what restricts it.
- **SSO-only since 2026-09-29**: password login removed (with two providers Hermes always shows a picker; with exactly
  one OAuth provider it auto-redirects to SSO). Break-glass if Zitadel/Cloudflare is down: over SSH run
  `~/.hermes/bin/set-dashboard-password` (re-adds `dashboard.basic_auth` only), then `systemctl restart hermes-dashboard`.
- (was: password login as LAN/netbird break-glass, login page showed both.) `bin/set-dashboard-password` now
  rewrites only `dashboard.basic_auth`, so it no longer wipes `public_url`/`oauth`.
- Binding `0.0.0.0` accepts any Host header, so LAN/netbird URLs keep working with `public_url` set.

### Update 2026-09-28: v0.21.4 → v0.21.5 (`0c380abe`)
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

## Second assistant: Luna (profile `luna`, added 2026-10-07)
A separate Hermes **profile** (`~/.hermes/profiles/luna`, own persona/memory/Honcho workspace `luna`) served headless by
the same multiplexed gateway's **OpenAI-compatible API server** (`192.168.4.101:8642`, `/p/luna/v1`, luna-only key),
with a multi-user **Open WebUI front end at https://luna.geekstyle.net**. Chat-only tools; not on Signal; no dashboard
(the dashboard is an owner console that can reach every profile). Full design, security checks and "adding a person":
[`../luna/README.md`](../luna/README.md).
- Changes to Mickey's side: `~/.hermes/.env` gained `API_SERVER_*` (API server on, bound to 192.168.4.101); default
  profile's `platform_toolsets.api_server` is chat-only. Mickey's Signal setup is unchanged.

## Operations
```bash
hermes chat                                   # talk to Mickey in the terminal (full tools)
hermes honcho status                          # memory link
hermes pairing list | hermes pairing approve signal <CODE>
sudo systemctl status hermes-gateway signal-cli
journalctl -u hermes-gateway -f               # logs
sudo systemctl restart hermes-gateway         # after config/.env/SOUL.md changes (or /restart in chat)
curl -s http://127.0.0.1:8093/api/v1/rpc -d '{"jsonrpc":"2.0","id":1,"method":"listGroups"}'   # groups Mickey is in
```
New group → add Mickey on the phone → get its ID with `listGroups` → append to `SIGNAL_GROUP_ALLOWED_USERS`
(comma-separated, **no inline comment on that line**) → restart the gateway.

**Deleting Mickey's posts ("delete for everyone", ~24 h window).** Hermes doesn't store Signal sent-timestamps, so:
1. `sudo systemctl stop hermes-gateway` (also stops him reacting); listen: `curl -sN http://127.0.0.1:8093/api/v1/events > events.log &`
2. React with any emoji to each post to delete — each reaction carries `targetSentTimestamp` of the reacted-to message.
3. For each timestamp: `{"jsonrpc":"2.0","id":1,"method":"remoteDelete","params":{"groupId":"<id>","targetTimestamp":<ts>}}`
   to `/api/v1/rpc` (only the bot's own messages can be deleted).
4. Kill the listener **by PID** (a `pkill -f` pattern matches its own shell), check the ledger queue is empty, start the gateway.

To see which group member is unreachable without posting anything: `sendTyping` with `"stop": true` to the group
returns per-recipient results (`UNREGISTERED_FAILURE` + `recipientAddress.uuid`).

Per-chat tone without a new bot: `signal.channel_prompts` in config.yaml (key `group:<groupId>`) — **only with the local patch**: upstream's Signal adapter never passes it on (corrected 2026-09-24; earlier notes said it worked). A differently
*named* bot needs its own Signal number + Hermes profile (`hermes profile create <name>`).

## Log
- 2026-09-24 — Hermes installed on node1; persona Sorcerer Mickey; Honcho workspace `hermes`; model qwen3.8:27b on
  Ollama → switched to claude-sonnet-5 (4× faster). Signal via signal-cli (Java 25 + ARM64 libsignal), dedicated
  number registered by voice; DM pairing; Signal made chat-only; group "Disney Gang 2025" allowed with name-trigger
  wake-up (local patch). Hermes updated to 88dee3e866 (by Mickey, on request).
- 2026-09-24 — Group incident: 4 duplicate posts (unregistered member → whole send treated as failed → ledger re-sends)
  and reasoning shown in every message. Gateway stopped, stuck delivery abandoned, send-result patch + Signal
  `show_reasoning: false`, restarted with nothing replayed.

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
- **Login (one-time, interactive):** `hermes mcp login gitlab` on node1 → open the printed URL → Authorize. The redirect
  goes to `http://127.0.0.1:27890/callback` on node1: either `ssh -N -L 27890:127.0.0.1:27890 ubuntu@192.168.4.101`
  first, or paste the failed redirect URL back into the prompt. Tokens: `~/.hermes/mcp-tokens/gitlab*.json` (0600).
- **Check:** `hermes mcp test gitlab` lists the tools; gateway log shows `MCP: registered 27 tool(s) from 1 server(s)`.

## Mac Studio models in the /model menu (2026-10-08)

Named provider **`mac-studio`** ("Mac Studio (Ollama)") in `~/.hermes/config.yaml` → `providers:` —
`base_url: http://100.101.193.15:11434/v1` (netbird), `transport: chat_completions`, `default_model: qwen3.8:27b`,
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

Local patch (in `~/.hermes/local-patches/signal-local.patch`, re-applied after every `hermes update`; it now also carries the Haiku 5.5 defaults above), Signal analogue
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

`mcp/s3_store.py` — a small stdio MCP server (installed as `~/.hermes/local-mcp/s3_store.py`, run with the Hermes venv's
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
Cheshire's picker → Opus / Sonnet / Haiku each correct. Patch carried in `~/.hermes/local-patches/signal-local.patch`.

**Default models:** Mickey `claude-sonnet-5-5`; Cheshire `claude-opus-5-5` (+ picker); Luna `claude-opus-5-5` (2026-10-09).

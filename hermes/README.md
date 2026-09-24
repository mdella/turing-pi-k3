# Hermes Agent — "Sorcerer Mickey" on k3-node1 (CLI + Signal)

[Hermes Agent](https://github.com/NousResearch/hermes-agent) (Nous Research) running on **k3-node1** as
**Sorcerer Mickey**: a personal assistant reachable from the terminal and from **Signal** (DM + one group chat),
thinking with **Claude Sonnet 5** and remembering through the self-hosted **Honcho** (`../honcho/`).
Set up 2026-09-24.

> Public repo: phone numbers, the Signal group ID, Signal UUIDs, the Honcho token and the Anthropic key are
> **not** in these notes — they live only in `~/.hermes/` on node1 (placeholders below).

## At a glance
| Part | Value |
|---|---|
| Hermes | v0.21.4, `~/.hermes/hermes-agent` (git checkout, user install as `ubuntu`), command `~/.local/bin/hermes` |
| Persona | `~/.hermes/SOUL.md` (copy: [`SOUL.md`](SOUL.md)); original saved as `SOUL.md.orig` |
| Model | `claude-sonnet-5` (provider `anthropic`), working context capped at 200K (`model.context_length`) |
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
hermes config set model.default claude-sonnet-5
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
| Signal DM | paired users only (`hermes pairing approve signal <CODE>`); unknown DMs get a pairing code | **chat-only** |
| Signal group "Disney Gang 2025" (22 members) | anyone in that group, only when Mickey is addressed | **chat-only** |

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
"Sorcerer Mickey", or ends with ", Mickey?". Ordinary Disney talk ("meet Mickey at Toontown", "Mickey pretzels") is
ignored and never leaves node1. Patterns (tested 10/10) are in `config.yaml`:
```yaml
signal:
  mention_patterns:
    - '^\W*(?:(?:hey|hi|hello|ok|okay|yo|so)\W+)?(?:sorcerer\s+)?mick(?:e)?y\s*[,:!?]'
    - '^\W*(?:(?:hey|hi|hello|ok|okay|yo|so)\W+)?(?:sorcerer\s+)?mick(?:e)?y\s+(?:what|when|where|who|why|how|can|could|would|will|do|does|is|are|please|pls|tell|find|remind|check|help|look)\b'
    - '\bsorcerer\s+mick(?:e)?y\b'
    - ',\s*(?:sorcerer\s+)?mick(?:e)?y\s*[?!.]*\s*$'
```
A "silent listener" (see every message, reply only when useful via Hermes' `[SILENT]` marker) was considered and
declined: every group message would become a Sonnet call and all 22 people's messages would go to Anthropic/Honcho.

**Data flow:** addressed messages + replies → Anthropic (Sonnet 5) and Honcho (stored; conclusions extracted by the
local Mac coder; memory questions on Sonnet every 3 turns). Tell the group Mickey is an AI with memory.

## Local patch (re-apply after `hermes update`)
[`patches/signal-local.patch`](patches/signal-local.patch) makes two changes to `gateway/platforms/signal.py`:
1. **Name trigger:** upstream's Signal adapter ignores `mention_patterns` (only WhatsApp/BlueBubbles implement it);
   the patch adds it (~10 lines, reusing `compile_mention_patterns`).
2. **Group duplicate fix:** upstream `_validate_send_result` failed the whole send if **any** recipient result wasn't
   `SUCCESS`. One group member with a deleted Signal account (`UNREGISTERED_FAILURE`) made every group reply "fail",
   and the delivery ledger re-sent it to everyone as "Recovered reply … may be a duplicate" (4 posts on 2026-09-24).
   Now: success if at least one recipient accepted it; per-recipient failures are logged. DMs unchanged.
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

Per-chat tone without a new bot: `channel_prompts` (works on Signal via the shared gateway key). A differently
*named* bot needs its own Signal number + Hermes profile (`hermes profile create <name>`).

## Log
- 2026-09-24 — Hermes installed on node1; persona Sorcerer Mickey; Honcho workspace `hermes`; model qwen3.8:27b on
  Ollama → switched to claude-sonnet-5 (4× faster). Signal via signal-cli (Java 25 + ARM64 libsignal), dedicated
  number registered by voice; DM pairing; Signal made chat-only; group "Disney Gang 2025" allowed with name-trigger
  wake-up (local patch). Hermes updated to 88dee3e866 (by Mickey, on request).
- 2026-09-24 — Group incident: 4 duplicate posts (unregistered member → whole send treated as failed → ledger re-sends)
  and reasoning shown in every message. Gateway stopped, stuck delivery abandoned, send-result patch + Signal
  `show_reasoning: false`, restarted with nothing replayed.

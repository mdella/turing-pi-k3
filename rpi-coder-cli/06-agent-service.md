# 06: Goose as an always-on agent service

Goose runs on the Pi as a **systemd user service** exposing the Agent Client Protocol (ACP) over HTTP + SSE.
Any machine on netbird with the shared secret can open a session and have the Pi's Goose work: shell, files,
MCP tools, with **qwen3-coder-next on the Mac Studio** as the model. Set up and verified 2026-09-23.

```
client (any netbird peer) ──ACP/HTTP+SSE, X-Secret-Key──▶ Pi 100.101.77.5:3284  goose serve
                                                              │  tools run on the Pi, in ~/agent-workspace
                                                              └──OpenAI API──▶ Mac 100.101.193.15:8080 qwen3-coder-next
```

## The service
| | |
|---|---|
| Unit | `~/.config/systemd/user/goose-agent.service` ([copy](scripts/goose-agent.service)) |
| Command | `goose serve --host 100.101.77.5 --port 3284` |
| Listens on | **netbird only** (`100.101.77.5:3284`). Not on the Pi's LAN/Wi-Fi addresses (verified: no answer on 192.168.1.217) |
| Starts | at boot, without anyone logged in (`loginctl enable-linger mdella`); `Restart=always` every 10 s, which also covers netbird coming up after the service |
| Working dir | `~/agent-workspace` (default `cwd`; clients can pass another in `session/new`) |
| Config | same as interactive Goose: `~/.config/goose/config.yaml` (model, 64K limit, compaction 0.6) |
| Secret | `~/.config/goose/serve.env` → `GOOSE_SERVER__SECRET_KEY` (64 hex chars, mode 600, generated on the Pi, not in git) |
| Model settings | `~/.config/goose/llm.env` (the `local-llm.env` values without `export`, for systemd) |

Manage it on the Pi:
```bash
systemctl --user status goose-agent
systemctl --user restart goose-agent        # after changing config.yaml
journalctl --user -u goose-agent -f
systemctl --user disable --now goose-agent  # turn it off
```

## Security: read this before handing out the secret
- **Anyone with the secret gets a shell on the Pi as `mdella`, and `mdella` has passwordless sudo.** Sessions start in
  Goose's `auto` mode (tool calls approved without asking). Treat the secret like an SSH key.
- Unauthenticated requests are refused: `/acp` returns **401** without or with a wrong `X-Secret-Key` (verified from
  the Mac). `/health` and `/status` answer without auth (they reveal only that the service is up).
- No TLS: traffic between netbird peers is already encrypted by WireGuard. Add `--tls` with a cert if the service is ever
  exposed beyond netbird.
- Clients can pick a safer mode per session: ACP `session/new` advertises `auto`, `approve` (ask before every tool
  call), `smart_approve` (ask for sensitive ones) and `chat` (no tools).
- Hardening options, not done: run the service as a dedicated user without sudo; set `GOOSE_MODE: smart_approve` in the
  config; rotate the secret by deleting `serve.env`, recreating it and restarting.

To give a client the secret, read it yourself from your own terminal (don't paste it into chats or commit it):
```bash
ssh mdella@rpi-sr-101-77-5.cstone.to 'cat ~/.config/goose/serve.env'
```

## Talking to it (protocol, as observed on goose 1.52)
Every request carries `X-Secret-Key: <secret>`. Endpoint `http://100.101.77.5:3284/acp`.

1. `POST /acp` JSON-RPC `initialize` → **200** with the result and an **`acp-connection-id`** response header.
2. `GET /acp` with `Accept: text/event-stream` + `acp-connection-id` → connection event stream (SSE).
3. `POST /acp` `session/new` `{cwd, mcpServers}` + `acp-connection-id` → **202**; the result (`sessionId`, available
   modes, config options) arrives on the **connection** stream.
4. `GET /acp` SSE with `acp-connection-id` **and `acp-session-id`** → session event stream.
5. `POST /acp` `session/prompt` + both headers → **202**; `session/update` notifications (`agent_message_chunk`,
   `tool_call`, `usage_update`…) and the final result (`stopReason`) arrive on the **session** stream.

The session stream is the non-obvious part: without it, a prompt is accepted (202) and the answer is never seen.

Reference client (stdlib Python, no dependencies): [`scripts/acp_client.py`](scripts/acp_client.py)
```bash
GOOSE_SERVER__SECRET_KEY=… python3 acp_client.py http://100.101.77.5:3284/acp /home/mdella/agent-workspace \
  "Use the shell to run: uname -m && hostname && pwd. Reply with the output only."
```

## Verified (2026-09-23)
| Check | Result |
|---|---|
| Service enabled, linger on, survives logout | ✅ `enabled`, `Linger=yes` |
| Bound to netbird only | ✅ `100.101.77.5:3284`; LAN address doesn't answer |
| From the Mac: `/health` | 200 |
| From the Mac: `/acp` without / with wrong secret | 401 / 401 |
| Full ACP session with a tool call | ✅ 2.6 s: `shell · uname -m && hostname && pwd` → `aarch64`, `rpi-sr-101.cstone.com`, `/home/mdella/agent-workspace` |
| Survives a reboot | not tested (reboot not performed); relies on linger + `WantedBy=default.target` |

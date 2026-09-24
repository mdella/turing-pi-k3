# 06: Goose as an always-on agent service

Goose runs on the Pi as a **systemd user service** exposing the Agent Client Protocol (ACP) over HTTP + SSE.
Any machine on netbird with the shared secret can open a session and have the Pi's Goose work: shell, files,
MCP tools, with **qwen3-coder-next on the Mac Studio** as the model. Set up and verified 2026-09-23.

```
client (any netbird peer) ──ACP/HTTP+SSE, X-Secret-Key──▶ Pi 100.101.77.5:3284  goose serve
                                                              │  tools run on the Pi as user goose, in /var/lib/goose-agent/workspace
                                                              └──OpenAI API──▶ Mac 100.101.193.15:8080 qwen3-coder-next
```

## The service
| | |
|---|---|
| Unit | `/etc/systemd/system/goose-agent.service` ([copy](scripts/goose-agent.service)), system service |
| Runs as | **`goose`** (uid 999): dedicated system user, **no sudo** (not in `sudo`, no sudoers entry), password locked, home `/var/lib/goose-agent` |
| Command | `/usr/local/bin/goose serve --host 100.101.77.5 --port 3284` |
| Listens on | **netbird only** (`100.101.77.5:3284`). Not on the Pi's LAN/Wi-Fi addresses |
| Starts | at boot (`WantedBy=multi-user.target`); `Restart=always` every 10 s, which also covers netbird coming up late |
| Working dir | `/var/lib/goose-agent/workspace` (default `cwd`; clients may pass another path under `/var/lib/goose-agent`) |
| Goose config | `/var/lib/goose-agent/.config/goose/config.yaml` (copy of mdella's: model, 64K limit, compaction 0.6) |
| Secret | `/etc/goose-agent/serve.env` → `GOOSE_SERVER__SECRET_KEY` (64 hex chars, `root:goose 640`, generated on the Pi, not in git) |
| Model settings | `/etc/goose-agent/llm.env` (`root:goose 640`) |
| Tools for the agent | `uv` in `/var/lib/goose-agent/.local/bin`; git identity `Goose agent (rpi-sr-101)` |

### Sandbox (systemd), since Goose runs arbitrary shell commands for its clients
| Setting | Effect |
|---|---|
| `User=goose` (no sudo) | tool calls run unprivileged |
| `NoNewPrivileges=yes` | setuid binaries (incl. `sudo`) can't raise privileges even if a rule existed |
| `ProtectHome=yes` | `/home` (mdella's files, SSH keys, gh token) is invisible |
| `ProtectSystem=strict` + `ReadWritePaths=/var/lib/goose-agent` | whole OS read-only; only its own home is writable |
| `PrivateTmp=yes`, `ProtectKernel*`, `ProtectControlGroups` | own `/tmp`; no kernel tunables/modules/cgroups |

Manage it on the Pi (as mdella):
```bash
systemctl status goose-agent
sudo systemctl restart goose-agent                       # after changing the config
sudo journalctl -u goose-agent -f
sudo -u goose -H nano /var/lib/goose-agent/.config/goose/config.yaml
sudo install -m 755 ~/.local/bin/goose /usr/local/bin/goose && sudo systemctl restart goose-agent   # after `goose update`
```
The service's Goose binary is a root-owned copy in `/usr/local/bin`: updating mdella's Goose doesn't update the
service until it's copied again.

History: first set up (same day) as a systemd *user* service running as mdella with linger. Replaced because mdella
has passwordless sudo: the secret was then root-equivalent. The old unit, its secret and mdella's linger were removed.

## Security
- **Anyone with the secret can run shell commands on the Pi as `goose`** in `/var/lib/goose-agent`: unprivileged,
  sandboxed as above, but with network access (it can reach the Mac, netbird peers, the internet). Sessions start
  in Goose's `auto` mode (tool calls approved without asking). Treat the secret like an SSH key.
- Unauthenticated requests are refused: `/acp` returns **401** without or with a wrong `X-Secret-Key`. `/health` and
  `/status` answer without auth (they reveal only that the service is up).
- No TLS: traffic between netbird peers is already encrypted by WireGuard. Add `--tls` with a cert if the service is ever
  exposed beyond netbird.
- Clients can pick a safer mode per session: ACP `session/new` advertises `auto`, `approve`, `smart_approve` and `chat`.
- Rotate the secret: `sudo sh -c 'umask 027; echo GOOSE_SERVER__SECRET_KEY=$(openssl rand -hex 32) > /etc/goose-agent/serve.env; chgrp goose /etc/goose-agent/serve.env'`
  then `sudo systemctl restart goose-agent`.

To give a client the secret, read it yourself from your own terminal (don't paste it into chats or commit it):
```bash
ssh mdella@rpi-sr-101-77-5.cstone.to 'sudo cat /etc/goose-agent/serve.env'
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
GOOSE_SERVER__SECRET_KEY=… python3 acp_client.py http://100.101.77.5:3284/acp /var/lib/goose-agent/workspace \
  "Use the shell to run: uname -m && hostname && pwd. Reply with the output only."
```

## Verified (2026-09-23), as user `goose`
| Check | Result |
|---|---|
| Service enabled at boot, running as `goose` | ✅ system unit, `enabled`, `active (running)` |
| `goose` can't use sudo | ✅ `sudo -l -U goose`: *not allowed to run sudo*; inside the service `sudo -n true` → blocked by no-new-privileges, exit 1 |
| Bound to netbird only | ✅ `100.101.77.5:3284`; LAN address doesn't answer |
| From the Mac: `/acp` with a wrong secret | 401 |
| Agent's own probes, via a real ACP session | `id` → `uid=999(goose) … groups=991(goose)`; `ls /home/mdella` → *Permission denied*; `touch /etc/…` → *Read-only file system*; write + read in `workspace` ✅; `uv --version` ✅ |
| Full ACP session with tool calls | ✅ 6 shell tool calls in one prompt, all reported correctly |
| Survives a reboot | not tested (reboot not performed) |

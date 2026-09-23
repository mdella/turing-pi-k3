# Agent harnesses on the Raspberry Pi → Mac Studio coder

Goal: run terminal coding agents on a **Raspberry Pi 5** (`rpi-sr-101`) whose model is the
**qwen3-coder-next** served by `llama-server` on the Mac Studio. The Pi does no inference itself;
it only runs the agent program. Companion to [`node1-coder-cli/`](../node1-coder-cli/), which did the
same for k3-node1 and whose test plan is reused here.

| # | Note | Status |
|---|---|---|
| 01 | [Host & endpoint](01-host-endpoint.md): the Pi, the network path, what's reachable | ✅ verified 2026-09-23 |
| 02 | [Install & configure](02-install-config.md): uv, Claude Code, Aider, Goose | ✅ installed 2026-09-23 |
| 03 | [Tests & results](03-test-results.md): node1 test plan 1–7, per harness | 🟡 1–4 done; Aider 5–6 done; rest running |
| 04 | [Open questions](04-open-questions.md): context limits, auth, which harness to standardise on | 🟡 open |
| 05 | [**How to use them**](05-how-to-use.md): which agent when, everyday commands, settings, troubleshooting | ✅ |

## Quick facts
- Pi: Raspberry Pi 5, 4 GB, Debian 13 (trixie) aarch64, netbird `100.101.77.5`. SSH `mdella@rpi-sr-101-77-5.cstone.to`.
- Endpoint: `http://100.101.193.15:8080` (Mac Studio over netbird), model id `qwen3-coder-next`, no API key,
  4 shared slots × 64K context. Both the OpenAI (`/v1/chat/completions`) and Anthropic (`/v1/messages`) APIs work.
- The Pi is on a **different site** from the Mac's home LAN (`192.168.1.x` / `192.168.7.x`, ~50 ms RTT), so it
  always goes over netbird. No netbird ACL change was needed: 8080, 11434 and 8199 are all reachable.
- Harnesses installed: **Claude Code 2.1.280, Aider 0.86.2, Goose 1.52.0** (+ uv 0.12.18).

## Log
- 2026-09-23: Pi reachable over netbird; SSH key for `mdella@Richards-Mac-Studio` installed. From the Pi:
  llama-server `/health` 200 (0.08 s), Ollama 0.34.3, ComfyUI 200. Tool-call request returned a correct
  `tool_calls` in ~3 s.
- 2026-09-23: Installed uv + Claude Code (native installer, `~/.local/bin`). Claude Code drives llama-server
  directly via `/v1/messages`, no translation proxy needed (contrary to the assumption in node1 02).
- 2026-09-23: Installed git (apt), Aider (`uv tool install`), Goose (release script); configured both for the coder.
- 2026-09-23: Tests 1–3 for all three harnesses. All pass. Base prompts: Aider **611**, Goose **4,905**,
  Claude Code **18,109** tokens.
- 2026-09-23: Test 4 (rename) ✅ Aider 25 s, Goose 37 s. Test 6 cold wake: Aider 7.5 s. Test 5, Aider: 16/16 turns,
  peak 37.7K, but turn 14 was a silent no-op (edit-format mismatch, exit 0). Test scripts in `scripts/`.
- 2026-09-23: Added `claude-mac` wrapper, `gh` 2.46 (Debian) on the Pi, and the [how-to-use guide](05-how-to-use.md).

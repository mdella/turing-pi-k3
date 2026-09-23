# 01: Host & endpoint

## The Pi
| | |
|---|---|
| Hostname | `rpi-sr-101` (DNS `rpi-sr-101-77-5.cstone.to`) |
| Board | Raspberry Pi 5 Model B Rev 1.0, 4 cores, 4 GB RAM, 59 GB microSD |
| OS | Debian 13 (trixie), kernel 6.18.50+rpt-rpi-2712, aarch64, Python 3.13.5 |
| Interfaces | `wt0` netbird **100.101.77.5**, `eth0` 192.168.1.217, `wlan0` 192.168.7.136 |
| Access | `ssh mdella@rpi-sr-101-77-5.cstone.to` (key auth; passwordless sudo) |

4 GB RAM rules out useful local inference: the Pi is a client only.

## What the Pi can reach (measured from the Pi, 2026-09-23)
| Service on the Mac (`100.101.193.15`) | Port | Result |
|---|---|---|
| llama-server, `qwen3-coder-next` (80B-A3B, Q4_K_M) | 8080 | `/health` 200 in 0.08 s |
| Ollama 0.34.3 (other models, on demand) | 11434 | `/api/version` OK |
| ComfyUI (FLUX.2) | 8199 | 200 |

Round trip Pi ↔ Mac is ~50 ms (different site). Negligible next to model time.

A tool-calling request from the Pi (`get_weather` schema, `/v1/chat/completions`) returned
`finish_reason: tool_calls` with correct arguments in ~3 s.

## Why llama-server rather than Ollama
- Always loaded (sleeps after 5 idle min, ~3 s warm reload), 4 parallel slots, 64K context per slot.
- Ollama on the Mac is `MAX_LOADED_MODELS=1` and shares the 96 GB with llama-server (~53 GB resident):
  large Ollama models force `ai-mem big`, which stops the coder. See [`../mac-studio-flux2/ai-mem`](../mac-studio-flux2/ai-mem).

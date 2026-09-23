# 01 — The coder endpoint

What node1 talks to, and what was verified from node1 on 2026-09-23.

## Server side (Mac Studio)
| Item | Value |
|---|---|
| Engine | llama.cpp `llama-server` b10964, launchd daemon `com.cstone.llama-server` (runs as jax) |
| Model | official `Qwen/Qwen3-Coder-Next-GGUF` Q4_K_M (79.7B MoE, ~3B active), alias `qwen3-coder-next` |
| API | OpenAI-compatible: `/v1/models`, `/v1/chat/completions`, `/v1/completions`; also `/health`, `/props`, `/slots`, `/metrics` |
| Slots | `--parallel 4`, `-c 131072` → **4 slots × 32,768 tokens** |
| Idle | `--sleep-idle-seconds 300`: unloads after 5 min (47 GB → 0.2 GB), reloads on next request |
| Auth | none (same as Ollama on :11434) |

## Verified from node1
| Check | Result |
|---|---|
| `GET /health` via netbird IP | HTTP 200, 0.10 s |
| `GET /health` via `richards-mac-studio.cstone.to` | HTTP 200 (name resolves to 100.101.193.15 / fdec:… ULA) |
| `GET /v1/models` | `["qwen3-coder-next"]` |
| `GET /props` | 4 slots, n_ctx 32768 per slot, chat template includes tool support |
| Tool call (`tools=[run_shell]`, "list files in /etc") | `finish_reason: tool_calls`, `run_shell {"command":"ls /etc"}` — correct OpenAI format |
| Throughput (earlier test) | ~61 t/s for one user; 121 t/s total at 4 users (~31 t/s each) |

## Reproduce
```bash
curl -s http://100.101.193.15:8080/health
curl -s http://100.101.193.15:8080/v1/models
curl -s http://100.101.193.15:8080/props | python3 -m json.tool | head -40
```

## If it stops answering
1. On the Mac: `/usr/local/bin/ai-mem status` — someone may have run `ai-mem big` (coder stopped until `ai-mem coder`).
2. Log: `/Users/Shared/llama-models/llama-server.log`.
3. netbird on node1: `netbird status` (Management/Signal connected).

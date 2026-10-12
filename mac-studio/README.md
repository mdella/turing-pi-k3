# Mac Studio — Local AI Host

The Mac Studio sits alongside the Turing Pi cluster as the lab's GPU box: it serves local LLMs and image generation that the RK1 nodes can't, reached from the cluster and the Raspberry Pi agent host over NetBird.

**Hardware:** M3 Ultra, 28-core CPU, 60-core GPU, 96 GB unified memory, macOS 26. Multi-user host, usually reached over SSH.

## Contents

| Section | What's there |
|---|---|
| [Benchmarks](benchmarks/README.md) | Local coding-model benchmarks — every `claude-local` round (qwen3.6, qwen3.8, qwen3-coder-next, Kimi distill, abliterated models), the scoring method, raw results and the harness |
| [FLUX.2 / ComfyUI / LLM servers](flux2/README.md) | ComfyUI + FLUX.2 setup, the `llama-server` and ComfyUI LaunchDaemon plists, the `ai-mem` memory hand-off script, the FLUX.2 MCP server |
| [Pi agent → Mac](../rpi-coder-cli/README.md) | Raspberry Pi coding agents (Goose, Aider, Claude Code) driving the Mac's `llama-server` |

## Services

| Port | Service | Notes |
|---|---|---|
| 11434 | Ollama | On-demand models, `/api`, OpenAI and Anthropic `/v1/messages` APIs. `MAX_LOADED_MODELS=1`, 32 K default context (`OLLAMA_CONTEXT_LENGTH=32768` since 2026-09-22), `NUM_PARALLEL=4` (`qwen3next` models forced to 1 slot), KV cache q8_0. |
| 8080 | llama.cpp `llama-server` | `qwen3-coder-next` (80B-A3B, Q4_K_M, ~49 GB loaded), launchd daemon `com.cstone.llama-server`; sleeps after 5 idle min (`--sleep-idle-seconds 300`, ~0.2 GB) and reloads on the next request; 4 slots × 64 K context, tool calls supported. |
| 8188 | Caddy → ComfyUI :8189 | Password-protected front for the local ComfyUI (Krea 2, FLUX.1/2, Qwen-Image, Chroma). |
| 8199 | ComfyUI (headless, `com.cstone.comfyui`) | Second ComfyUI instance (FLUX.2) using the Comfy Desktop venv and shared model store; Comfy Desktop.app must be quit so it doesn't hold 8199. See [flux2](flux2/README.md). |

**Memory is the constraint.** `llama-server` holds ~49 GB while awake, so any Ollama model over ~40 GB won't fit next to it; `ai-mem big` / `ai-mem coder` hands the memory back and forth. No LLM endpoint has authentication — trusted network only.

## Image-generation notes

- **fp8 UNets don't run on Apple Silicon** (`Undefined type Float8_e4m3fn` — MPS has no fp8 conversion). Use bf16 or GGUF weights for the diffusion model; fp8 *text encoders* are fine.
- Working stacks: Krea 2 Turbo bf16, FLUX.1-Krea-dev Q8_0 GGUF, Qwen-Image-2512 Q8_0 GGUF (+ 4-step Lightning LoRA), Qwen-Image-Edit-2511 Q8_0 GGUF.

# 05 — Risks & open questions

## 1. Is 32K per slot enough? — ✅ resolved 2026-09-23: raised to 64K
Qwen Code's base prompt measured 17.1K tokens with all tools (see 04), so the plist now uses `-c 262144 --parallel 4`.
Cost: +1.6 GB resident (47.2 → 48.8 GB). A 53.5K-token prompt from node1 worked. Note: a brand-new ~50K prompt takes ~1 min to process;
later turns reuse the slot's prompt cache. 
**Decision 2026-09-23: stay at 64K** (128K considered and declined). Test 5's overflow was fixed by setting Qwen Code's
`contextWindowSize: 65536`, not by more memory: with it, auto-compaction holds the prompt at ~30–35K. 128K would cost
~+3.2 GB (≈52 GB loaded), slow long prompts and shrink Ollama's safe budget to ~30 GB; its only gain is less compaction
(better recall of early turns). Revisit only if losing early-session detail hurts real work — then `-c 524288` in the plist
+ `contextWindowSize: 131072` in each user's settings. Original analysis kept below.

### Original analysis
Agent CLIs send a large system prompt plus tool definitions on every request, before any code.
If that alone is 15–20K tokens, little is left for files and conversation.
- **Measure first** (test 2 in [04](04-test-plan.md)).
- If too small: raise the per-slot context. Options on the Mac plist: `-c 262144 --parallel 4` (64K each) or
  `-c 131072 --parallel 2` (64K each, fewer users). The model supports 256K and only part of its layers
  use a KV cache, so 64K/slot is likely affordable — check memory with `ai-mem status` after the change.

## 2. No authentication on :8080
Anyone who can reach the Mac on 8080 (netbird peers, and the LAN since it binds 0.0.0.0) can use the coder —
same as Ollama today. Option: add `--api-key <key>` to the llama-server plist and give the key to each CLI
(every candidate supports an API key setting). Decide before inviting other users.

## 3. Wake time after idle
First request after 5 idle minutes reloads the model: ~3 s if the files are still cached, **25–50 s** if a large
Ollama model pushed them out. Check each CLI's request timeout tolerates this (test 6). If not: raise
`--sleep-idle-seconds`, or send a warm-up request when starting the CLI.

## 4. Shared capacity — ✅ measured 2026-09-23: 4 concurrent OpenCode sessions all pass, ~28 t/s each (113 aggregate), task time ~2× solo. See [04](04-test-plan.md).
4 slots total across all users and all their sessions. Agent CLIs that run sub-agents in parallel use
several slots at once. Throughput per user falls from ~61 t/s (alone) to ~31 t/s (4 busy).

## 5. The coder can be switched off
`ai-mem big` on the Mac stops llama-server for large Ollama jobs; the CLI then gets connection errors until
`ai-mem coder` runs. Worth agreeing how people announce that.

## 6. Other clients (later)
- Home-LAN laptops aren't on netbird: they'd need a node1 forwarder `192.168.4.101:8080 → 100.101.193.15:8080`
  (same pattern as the ComfyUI `comfyui-forward.service`).
- Ollama's own copies of the coder (q4 + q8 tags, 137 GB) are now redundant and serialize requests —
  removal pending a decision.

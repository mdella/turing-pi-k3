# Coding-agent CLI on k3-node1 → Mac Studio coder

Goal: run a terminal coding agent on **k3-node1** whose model is the **qwen3-coder-next** served by
`llama-server` on the Mac Studio, instead of a cloud model.

| # | Note | Status |
|---|---|---|
| 01 | [The coder endpoint](01-endpoint.md) — what node1 connects to, verified facts | ✅ verified 2026-09-23 |
| 02 | [Choosing the CLI](02-cli-options.md) — candidates and recommendation | ✅ trials done — OpenCode recommended |
| 03 | [Install & configure on node1](03-install-config.md) — per-CLI steps | ✅ Qwen Code 0.24.4 + OpenCode 1.18.32 installed |
| 04 | [Test plan](04-test-plan.md) — what "works" means, how to measure it | ✅ Qwen Code and OpenCode pass 1–7 |
| 05 | [Risks & open questions](05-open-questions.md) — context size, auth, wake time, laptop access | 🟡 §1 (64K/slot) and §4 (capacity) resolved, rest open |
| 06 | [**How to use it**](06-how-to-use.md) — which app, settings, everyday commands, troubleshooting, re-running tests | ✅ |

## Quick facts
- Endpoint: `http://100.101.193.15:8080/v1` (or `http://richards-mac-studio.cstone.to:8080/v1`), model id `qwen3-coder-next`, no API key.
- Path: node1 → netbird → Mac. node1 is the only cluster node on netbird.
- Capacity: 4 simultaneous requests shared by **everyone** using the coder, **64K context each** (raised from 32K on 2026-09-23).
- The coder sleeps after 5 idle minutes; the first request after that waits for it to reload.
- Background: `k3s-cluster-notes.md` → "Multi-user coder: llama-server on the Mac Studio".

## Log
- 2026-09-23 — endpoint verified from node1 (health, models, tool calling). Notes series started.
- 2026-09-23 — Qwen Code 0.24.4 installed (user prefix). Test 1 ✅; test 2: 17.1K-token base prompt with all tools (tight in 32K); auto-memory adds a 10K request per turn → disabled.
- 2026-09-23 — Per-slot context raised 32K → **64K** (`-c 262144 --parallel 4`): +1.6 GB (47.2 → 48.8 GB). Verified from node1 with a 53.5K-token prompt (answered correctly; 66 s to process from scratch, ~800 t/s).
- 2026-09-23 — Qwen Code tests 3–5 ✅. Test 5 first overflowed at turn 6 (Qwen Code didn't know the 64K window); fixed with `contextWindowSize: 65536` in `~/.qwen/settings.json`, then 16/16 turns with prompt held at 30–35K. Also set `outputLanguage: English` (model drifted into Chinese).
- 2026-09-23 — Qwen Code tests 6–7 ✅: cold wake 40 s with a 28K uncached prompt; 2 concurrent sessions ~41 t/s each vs 57 solo. Fixed the English-output setting (`~/.qwen/output-language.md` must be regenerated). **Qwen Code is usable on node1**; OpenCode/Aider comparisons still open.
- 2026-09-23 — OpenCode 1.18.32 passes tests 1–7: base prompt 9.4K (vs 17.1K), 16-turn session ~14 min (vs ~37), English by default; weaker recall of early turns after compaction. Recommended as the default CLI.
- 2026-09-23 — 4-session load test (OpenCode): all pass, ~28 t/s each / 113 aggregate. Added [06 How to use](06-how-to-use.md) and `scripts/` (logging proxy, slot poller).

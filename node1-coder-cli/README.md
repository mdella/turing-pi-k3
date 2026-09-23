# Coding-agent CLI on k3-node1 → Mac Studio coder

Goal: run a terminal coding agent on **k3-node1** whose model is the **qwen3-coder-next** served by
`llama-server` on the Mac Studio, instead of a cloud model.

| # | Note | Status |
|---|---|---|
| 01 | [The coder endpoint](01-endpoint.md) — what node1 connects to, verified facts | ✅ verified 2026-09-23 |
| 02 | [Choosing the CLI](02-cli-options.md) — candidates and recommendation | 📝 decided: trial Qwen Code first |
| 03 | [Install & configure on node1](03-install-config.md) — per-CLI steps | 🟡 Qwen Code 0.24.4 installed |
| 04 | [Test plan](04-test-plan.md) — what "works" means, how to measure it | 🟡 Qwen Code tests 1–2 done |
| 05 | [Risks & open questions](05-open-questions.md) — context size, auth, wake time, laptop access | ⏳ open |

## Quick facts
- Endpoint: `http://100.101.193.15:8080/v1` (or `http://richards-mac-studio.cstone.to:8080/v1`), model id `qwen3-coder-next`, no API key.
- Path: node1 → netbird → Mac. node1 is the only cluster node on netbird.
- Capacity: 4 simultaneous requests shared by **everyone** using the coder, 32K context each.
- The coder sleeps after 5 idle minutes; the first request after that waits for it to reload.
- Background: `k3s-cluster-notes.md` → "Multi-user coder: llama-server on the Mac Studio".

## Log
- 2026-09-23 — endpoint verified from node1 (health, models, tool calling). Notes series started.
- 2026-09-23 — Qwen Code 0.24.4 installed (user prefix). Test 1 ✅; test 2: 17.1K-token base prompt with all tools (tight in 32K); auto-memory adds a 10K request per turn → disabled.

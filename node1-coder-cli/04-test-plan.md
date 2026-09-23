# 04 — Test plan

Status: ⏳ not started. Run each CLI against the same tasks in a throwaway git repo on node1
(e.g. `~/cli-trial/`), so results are comparable.

## What to measure
| # | Test | How | Pass if |
|---|---|---|---|
| 1 | Connects | Start the CLI, ask a one-line question | Answer arrives; model shows as `qwen3-coder-next` |
| 2 | Prompt fits | Watch llama-server `/slots` (or `/metrics` prompt tokens) on the first request | CLI's system prompt + tools **well under 32K** (leave ≥ 12K for work) |
| 3 | Tool loop | "Create `fizzbuzz.py`, run it, fix any error" | Writes file, runs it, iterates without malformed tool calls |
| 4 | Multi-file edit | "Rename function X across the repo and update tests" | Edits correct files; tests pass |
| 5 | Long session | 15–20 turns on one task | No context-overflow errors; still coherent |
| 6 | Cold wake | Leave idle > 5 min, then send a request | CLI waits (doesn't time out) through the reload |
| 7 | Shared load | Run 2 CLI sessions at once (+ another user if possible) | Both progress; note per-user speed |

## Useful commands during tests
```bash
curl -s http://100.101.193.15:8080/slots | python3 -m json.tool | grep -E '"id"|n_ctx|is_processing|n_past'
curl -s http://100.101.193.15:8080/metrics | grep -E 'prompt_tokens|tokens_predicted|requests_processing'
```

## Results
| Test | Qwen Code | OpenCode | Aider |
|---|---|---|---|
| 1 Connects | | | |
| 2 Prompt size (tokens) | | | |
| 3 Tool loop | | | |
| 4 Multi-file edit | | | |
| 5 Long session | | | |
| 6 Cold wake | | | |
| 7 Shared load | | | |

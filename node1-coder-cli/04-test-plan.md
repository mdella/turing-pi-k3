# 04 — Test plan

Status: 🟡 Qwen Code tests 1–2 done 2026-09-23. Run each CLI against the same tasks in a throwaway git repo on node1
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
| 1 Connects | ✅ correct answer; 31 s incl. cold wake, 12–17 s warm | | |
| 2 Prompt size (tokens) | ⚠️ 17,149 full tools (15.6K left) — passes ≥12K rule, but tight | | |
| 3 Tool loop | | | |
| 4 Multi-file edit | | | |
| 5 Long session | | | |
| 6 Cold wake | | | |
| 7 Shared load | | | |

## Qwen Code — test 2 detail (2026-09-23)
Measured from `--openai-logging` request logs (`usage.prompt_tokens`), trivial one-line prompt, trial repo `~/cli-trial`.

| Mode | Tools sent | Prompt tokens | Left of 32,768 |
|---|---|---|---|
| Interactive-equivalent (`--approval-mode yolo`, all tools) | 14 | **17,149** | 15.6K |
| One-shot default approval (edit/shell/write withheld) | 10 | 13,087 | 19.7K |
| `--bare` | 6 | 8,262 | 24.5K |
| Default + auto-memory **on** (main request) | 10 | 13,926 | — |
| └ auto-memory extractor sub-request, every turn | 6 | 10,247 | (2nd slot) |

Findings:
- Real sessions will start at ~17K before any file content — the 64K/slot change in [05](05-open-questions.md) §1 is advisable before serious use.
- Default auto-memory fires a second ~10K request after every turn → each user briefly holds **2 of 4** slots. Turn it off (see [03](03-install-config.md)).
- Qwen Code asks for `max_tokens: 32768` (the whole slot); llama-server caps generation at the context limit, so harmless, but note it if overflow errors show up in test 5.
- `--bare` saves ~9K but drops glob/grep/agent/skill tools — possible fallback if the context stays at 32K.

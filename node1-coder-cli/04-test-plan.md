# 04 — Test plan

Status: ✅ Qwen Code tests 1–7 done 2026-09-23 — passes all with the settings in [03](03-install-config.md). OpenCode/Aider not started. Run each CLI against the same tasks in a throwaway git repo on node1
(e.g. `~/cli-trial/`), so results are comparable.

## What to measure
| # | Test | How | Pass if |
|---|---|---|---|
| 1 | Connects | Start the CLI, ask a one-line question | Answer arrives; model shows as `qwen3-coder-next` |
| 2 | Prompt fits | Watch llama-server `/slots` (or `/metrics` prompt tokens) on the first request | CLI's system prompt + tools leave plenty of the slot for work (slot was 32K, now 64K) |
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
| 2 Prompt size (tokens) | ✅ 17,149 full tools — 15.6K left at 32K (tight) → 48.3K left at 64K (re-verified 17,210 on 2026-09-23) | | |
| 3 Tool loop | ✅ 35 s, 4 tool calls, tests pass, no malformed calls | | |
| 4 Multi-file edit | ✅ 47 s, 5 files, 0 leftovers, tests pass (summary came back in Chinese) | | |
| 5 Long session | ✅ after fix — 16/16 turns, 66 tests pass; ❌ without `contextWindowSize` (overflow at turn 6) | | |
| 6 Cold wake | ✅ 40 s from sleep with a 28K uncached prompt; no timeout | | |
| 7 Shared load | ✅ 2 sessions both pass; ~41 t/s each (83 aggregate) vs 57 t/s solo | | |

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
- Real sessions will start at ~17K before any file content — **done: slots raised to 64K on 2026-09-23** (≈48K left for work). See [05](05-open-questions.md) §1.
- Default auto-memory fires a second ~10K request after every turn → each user briefly holds **2 of 4** slots. Turn it off (see [03](03-install-config.md)).
- Qwen Code asks for `max_tokens: 32768` (the whole slot); llama-server caps generation at the context limit, so harmless, but note it if overflow errors show up in test 5.
- `--bare` saves ~9K but drops glob/grep/agent/skill tools — possible fallback if the context stays at 32K.

## Qwen Code — tests 3–5 detail (2026-09-23)
Harness: one-shot `qwen --approval-mode yolo`, one git repo per test under `~/cli-trial/t3..t5`, request logs via `--openai-logging`.

**Test 3** (fizzbuzz + unittest, fix until green): 5 requests, `write_file`×2 + `run_shell_command`×2, peak prompt 17.6K. Pass.

**Test 4** (rename `calc_total` → `compute_order_total` across 3 modules, tests, README): grep → read×5 → edit×5 → run tests.
5 requests, peak 19.5K, 0 leftovers, 3/3 tests pass. Final summary was in Chinese → `general.outputLanguage`.

**Test 5** (16 turns building a todo CLI, `--continue` between turns):
- **Run 1 — failed.** Prompt grew ~5–10K/turn (19K → 49K by turn 5); turn 6 hit
  `400 request (67846 tokens) exceeds the available context size (65536 tokens)`. Qwen Code never compacted because it
  didn't know the window (falls back to a model-name guess). Every later turn failed instantly: the session is unrecoverable.
- **Run 2 — pass** with `model.generationConfig.contextWindowSize: 65536`. Auto-compaction held the peak prompt at
  **30–35K** from turn 3 on (history dropped e.g. 56 → 24 messages between turns). 16/16 turns exit 0, 192 requests,
  0 API errors, 0 malformed tool-call args. Final: 6 modules, **66 tests, all pass**. Turns took 31–317 s (median ~2.5 min).
- Coherence after compaction: good on the current state (accurate file summary at turn 11; storage refactor at turn 12
  kept tests green), fuzzy on history — asked for the turn-1 function's signature, it named the right method
  (`TodoStore.add`) but gave today's signature, not the original `add(self, title)`.
- Language drift: docstrings, test data and the turn-11 answer were in Chinese (123 CJK lines in README alone) → now
  `general.outputLanguage: "English"` (not yet re-tested).
- Minor: `tests/` has no `__init__.py`, so `python3 -m unittest discover` finds 0 tests; `python3 -m unittest tests.test_store tests.test_cli` runs all 66.

## Qwen Code — test 7 detail (2026-09-23)
Same task (textstats module + unittest tests, fix until green) run solo, then as 2 concurrent sessions;
a poller sampled `/slots` every 2 s for busy slots and per-slot decode rate. No other users were active.

| Run | Wall time | Tests written / passing | Busy slots | Per-slot decode | Aggregate |
|---|---|---|---|---|---|
| Solo | 47 s | 8 / 8 | 1 | 57 t/s | 57 t/s |
| Concurrent A + B | 62 s, 68 s | 10 / 10, 9 / 9 | 2 | 41 t/s each | ~83 t/s |
| Concurrent C + D (after language fix) | 98 s, 84 s | 16 / 16, 12 / 12 | 2 | — | — |

- Two users cost each ~28 % speed; wall time grows less than that because tool execution and prefill overlap.
  Consistent with the earlier curl benchmark (61 t/s alone, ~31 t/s each at 4 busy).
- Peak prompt ~19K per session, 0 malformed tool calls, 0 API errors.
- A + B both answered in Chinese despite `outputLanguage: English` → found the `output-language.md` gotcha (see [03](03-install-config.md)); C + D after the fix: 0 CJK characters in answers or code.
- The model's run-to-run variation (47–98 s for the same task) is larger than the load effect, so single-run timings are only indicative.

## Qwen Code — test 6 detail (2026-09-23)
Waited until `/props` reported `is_sleeping: true` (02:49:45, ~5 min after the last request), then resumed the
test-5 session with `--continue` — the worst realistic case: model reload **plus** a full uncached prefill.
- First request: 28,190 prompt tokens, 0 cached; second: 28,324 with 28,250 cached. Answer correct (66). **40 s** total, no errors.
- This was a *warm-disk* reload (model files still in the Mac's page cache, ~3 s). The *cold-disk* case (files evicted
  by a big Ollama model, 25–50 s reload) couldn't be forced without disturbing other users.
- Risk: Qwen Code's per-request `timeout` defaults to **120 s**. Cold-disk reload (≤50 s) + a near-full 55K prefill at
  ~800 t/s (~70 s) could just exceed it. Stream idle timeout (240 s) is not a concern.
  Suggested if it ever bites: `"model": {"generationConfig": {"timeout": 300000}}` in `~/.qwen/settings.json`.

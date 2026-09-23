# 03: Tests & results

Test plan is node1's ([`../node1-coder-cli/04-test-plan.md`](../node1-coder-cli/04-test-plan.md)), run from the Pi.
Throwaway repos under `~/harness-tests/` on the Pi. Pass/fail is checked independently (re-running
`uvx pytest -q` ourselves), not taken from the agent's own summary.

## Summary (2026-09-23)
| Test | Claude Code 2.1.280 | Aider 0.86.2 | Goose 1.52.0 |
|---|---|---|---|
| 1 Connects | ✅ | ✅ | ✅ |
| 2 Base prompt (tokens) | **18,109**, 21 tools | **611**, no tool schemas | **4,905**, 17 tools |
| 2 Left of the 64K slot | ~47K | ~65K | ~60K |
| 3 Tool loop (fizzbuzz + pytest) | ✅ 30 s, 4 turns, 2/2 pass | ✅ 16 s, 2/2 pass | ✅ 15 s, 2/2 pass |
| 4 Multi-file rename | not run | ✅ 25 s, 3 requests, 0 leftovers, 4/4 | ✅ 37 s, 18 requests / 21 tool calls, 0 leftovers, 4/4 |
| 5 Long session (16 turns) | not run | 🟡 16/16 turns ran, 0 errors, peak 37.7K, 23/23 tests, **but turn 14 silently made no edits** | ✅ 16/16, 0 errors, 81/81 tests, all features work; auto-compacted at turn 11 **51 tokens short of the limit** |
| 6 Cold wake | not run | ✅ 7.5 s from sleep (warm disk) | ✅ 7.4 s from sleep (warm disk) |
| 7 Shared load | not run | ✅ 1/2/4 sessions all pass; 4 at once 36–60 s, ~26 t/s each | ✅ 1/2/4 sessions all pass; 4 at once 45–68 s, ~27 t/s each |

For comparison, node1 measured Qwen Code at 17.1K and OpenCode at 9.4K base prompt.

## Test 1: connects
Prompt "What is 2+2? Answer with only the number." All three answered `4`. Warm, the whole run took
1–5 s for Goose/Aider; Claude Code's first request took 18 s because its 18K-token prompt was not yet in
the slot's cache.

## Test 2: base prompt size
Measured by routing each harness through `node1-coder-cli/scripts/logproxy.py` on the Pi
(`127.0.0.1:18080` → Mac) with the trivial test-1 prompt. For Claude Code, the proxy can't parse Anthropic
streaming usage, so the figure is `input + cache_read + cache_creation` tokens from `claude -p --output-format json`
(1 turn, so one request).

| Harness | Requests for one question | Messages | Tools sent | Prompt tokens |
|---|---|---|---|---|
| Aider | 1 | 8 (system + example edit-format turns) | 0 | 611 |
| Goose | `/v1/models` + 1 | 2 | 17 (developer extension) | 4,905 |
| Claude Code | 1 | 2 | 21 | 18,109 |

- Aider doesn't use function calling at all: it asks for edits in its own text format and applies them itself.
  That's why its prompt is tiny, and why it's the least sensitive to tool-calling quirks.
- Claude Code's 18K is the same order as Qwen Code's; it leaves ~47K of the slot for real work.
- Goose's base prompt grows with every extension enabled; only `developer` is on.

## Test 3: tool loop
Same task for all three, each in a fresh git repo:
> Create fizzbuzz.py containing a function fizzbuzz(n) that returns a list of strings for 1..n (Fizz for multiples
> of 3, Buzz for 5, FizzBuzz for 15, otherwise the number). Also create test_fizzbuzz.py with pytest tests covering
> n=15 and n=0.

Goose and Claude Code were additionally told "Then run the tests with: uvx pytest -q, and fix anything that fails."

| Harness | Invocation | Wall | Independent `pytest` | Notes |
|---|---|---|---|---|
| Aider | `aider --yes-always --no-stream --message "…" fizzbuzz.py test_fizzbuzz.py` | 16 s | 2 passed | Makes git commits: one commit of the two empty files (message wrongly says "add implementation"), then one with the real code. Doesn't run tests itself unless configured (`--test-cmd`). |
| Goose | `goose run --no-session -t "…"` | 15 s | 2 passed | Wrote both files, ran `uvx pytest -q` itself, reported pass. |
| Claude Code | `claude -p "…" --dangerously-skip-permissions` | 30 s | 2 passed | 4 turns; ran the tests itself. |

0 malformed tool calls in any run.

## Test 4: multi-file rename
Script: [`scripts/t4-rename.sh`](scripts/t4-rename.sh). Fixture: `calc_total` defined in `shop/pricing.py`, imported in
`cart.py`, called as `pricing.calc_total` in `invoice.py`, used by 2 test modules and the README (5 files).
Prompt: rename to `compute_order_total` everywhere, then run the unit tests. Checked by us: `grep` for leftovers
and our own `python3 -m unittest` run.

| | Aider | Goose |
|---|---|---|
| Wall | 25 s | 37 s |
| Requests / tool calls | 3 / 0 (edits in Aider's own format) | 18 / 21 |
| Peak prompt | 2,007 | 7,999 |
| Leftover `calc_total` | 0 | 0 |
| Files with new name | 5 | 5 |
| Tests | 4/4 | 4/4 |
| Malformed tool calls / HTTP errors | 0 / 0 | 0 / 0 |

## Test 5: 16-turn session
Script: [`scripts/t5-long.sh`](scripts/t5-long.sh). One todo-CLI project built over 16 separate invocations (Aider:
`--restore-chat-history`, all tracked files added, `--auto-test`; Goose: named session resumed with `-r`).
Turns 1–10 and 12–15 add features; turn 11 asks for a file summary; turn 16 asks, from memory, for the signature of
the method created in turn 1. After every turn we run the unit tests ourselves; the proxy logs each turn's requests.

### Aider (2026-09-23): 16/16 turns, 0 HTTP errors, but one silent no-op
| Turn | Wall | Tests (ours) | Peak prompt |
|---|---|---|---|
| 1 | 69 s | 5/5 | 3,747 |
| 2–5 | 35–41 s | 7 → 19 | 3.8–5.2K |
| 6 | 97 s | 20/20 | 8,156 |
| 7–10 | 28–47 s | 20/20 | 9.3–12.7K |
| 11 (summary) | 100 s | 21/21 | 14,104 |
| 12 (refactor into `storage.py`) | 97 s | 21/21 | 19,866 |
| 13 (corrupt-file handling) | 211 s | 23/23 | 23,105 |
| 14 (`search` subcommand) | 107 s | 23/23 | 33,161 |
| 15 (README) | 36 s | 23/23 | 36,554 |
| 16 (recall) | 27 s | 23/23 | 37,670 |

Total ~20 min. Peak prompt 37.7K, so it never came near the 64K limit, and no compaction was needed.

Checked by driving the finished CLI ourselves: `add` with `--priority`/`--due`, sorted `list`, `overdue`, `done`,
`delete` and corrupt-file handling (clean one-line error, exit 1) all work.

**Failure: turn 14 made no changes and still exited 0.** The model answered with a plan and code snippets that
didn't follow Aider's edit format, so nothing was applied; `search` doesn't exist in the final CLI, and the tests
still passed because the tests it described were never written either. Aider was using the **`whole`** edit format
for this model, since it doesn't recognise it. A scripted Aider run therefore can't be trusted on exit code alone.
To try: `--edit-format diff` (smaller replies, closer to what the model does well), and check `git log` for a
new commit after every turn.

Turn 16 recall: named the right method but gave its **current** signature
(`add(self, title, priority='normal', due_date=None)`), not the original `add(self, title)`. That's the same partial
result Qwen Code got on node1.

Also seen: `Summarization failed … cannot schedule new futures after shutdown` at the end of some one-shot turns:
Aider's history summariser runs as the process exits in `--message` mode. Harmless here (history stayed small), but
history is not being summarised in scripted use.

### Goose (2026-09-23): 16/16 turns, 81/81 tests, every feature works, but the compaction was a near miss
| Turn | Wall | Tests (ours) | Peak prompt | Requests / tool calls |
|---|---|---|---|---|
| 1 | 41 s | 6/6 | 6,494 | 7 / 6 |
| 2 | 109 s | 15/15 | 11,724 | 9 / 8 |
| 3–5 | 24–59 s | 19 → 26 | 14.5–19.4K | 4–9 / 3–8 |
| 6 | 150 s | 42/42 | 29,523 | 10 / 9 |
| 7 | 142 s | 49/49 | 37,662 | 9 / 8 |
| 8 | 26 s | 49/49 | 39,466 | 4 / 3 |
| 9 | 217 s | 58/58 | 51,547 | 14 / 13 |
| 10 | 320 s | 68/68 | 62,544 | 12 / 11 |
| 11 (summary) | 122 s | 68/68 | **65,485** (compaction request) → 15.2K | 12 / 15 |
| 12 (refactor) | 20 s | 68/68 | 16,923 | 4 / 3 |
| 13–15 | 20–78 s | 70 → 81 | 21.3–31.0K | 3–16 / 2–15 |
| 16 (recall) | 3 s | 81/81 | 31,173 | 1 / 0 |

Total ~24 min, 0 HTTP errors, 0 malformed tool calls (~130 tool calls). Checked by driving the finished CLI
ourselves: `add --priority --due`, sorted `list`, `overdue`, `search` (case-insensitive), `done`, `delete` and
corrupt-file handling (one-line error, exit 1) all work. 162-line README.

**Compaction near miss.** Goose logged *"Exceeded auto-compact threshold of 80%. Performing auto-compaction"* at the
start of turn 11. But it only checks between turns: during turn 10 the prompt grew 51.7K → 62.5K without compacting,
and the summarising request itself was **65,485 tokens: 51 short of the 65,536 slot**. A slightly longer turn 10
would have overflowed with a 400. After compaction the prompt restarted at ~5K and the session carried on normally.
**Fix applied on the Pi after this test:** `GOOSE_CONTEXT_LIMIT: 65536` and `GOOSE_AUTO_COMPACT_THRESHOLD: 0.6` in
`~/.config/goose/config.yaml` (compact at ~39K, leaving ~26K headroom for a long turn). Not yet re-run with it.

Turn 16 recall: gave the **current** signature (`add(self, title, priority="normal", due=None)`) but correctly
noted that the original request "only specified `add(title)`". Closest of the three CLIs tested so far (node1:
Qwen Code current signature, OpenCode wrong method).

### Aider vs Goose on the same 16 turns
| | Aider | Goose |
|---|---|---|
| Total time | ~20 min | ~24 min |
| Peak prompt | 37.7K (no compaction needed) | 65.5K (compacted once, near miss) |
| Tests at the end | 23 | 81 |
| Features actually working | all but `search` (silent no-op) | all |
| Tool calls | 0 (own edit format) | ~130, 0 malformed |
| Recall of turn 1 | current signature | current signature + noted the original was `add(title)` |

## Test 6: cold wake
Waited for `/props` → `is_sleeping: true`, then sent a trivial request.
- **Aider: 7.5 s** end to end, correct answer (warm-disk reload: model files still in the Mac's page cache).
- **Goose: 7.4 s**, correct answer (script: [`scripts/t6-wake.sh`](scripts/t6-wake.sh)).
- Neither timed out. The slow case (model files pushed out of the Mac's page cache by a large Ollama model,
  25–50 s reload on node1) wasn't forced, to avoid disturbing other users.
- A first attempt at the Goose run was invalid (script bug: the logging proxy wasn't started). Goose printed
  `Network error: Could not connect` **and exited 0**, which is worth knowing for scripted use.

## Test 7: shared load
Script: [`scripts/t7-load.sh`](scripts/t7-load.sh). The same one-shot task (`textstats.py` with `word_count`,
`char_count`, `top_words` + unittest tests, run them, fix failures) started 1, 2 and 4 times at once in separate repos.
`slot-poll.py` sampled the Mac's `/slots` every 2 s. Tests checked by us in every repo.

| Agent × sessions | Wall per session | Tests (ours) | Busy slots (max) | Per-slot decode | Requests / tool calls |
|---|---|---|---|---|---|
| Aider × 1 | 49 s | 11/11 | 2* | 40 t/s | 4 / 0 |
| Aider × 2 | 46 s, 46 s | 11/11, 11/11 | 2 | 43 t/s | 8 / 0 |
| Aider × 4 | 36–60 s | 9–11, all pass | 4 | 26 t/s | 11 / 0 |
| Goose × 1 | 32 s | 18/18 | 1 | 54 t/s | 5 / 4 |
| Goose × 2 | 47 s, 66 s | 20/20, 17/17 | 2 | 34 t/s | 25 / 23 |
| Goose × 4 | 45–68 s | 15–17, all pass | 4 | 27 t/s | 28 / 24 |

\* During the Aider × 1 run a second slot was busy with a request that wasn't ours (another user of the coder),
so that row's speed is lower than a true solo run.

- 0 HTTP errors and 0 malformed tool calls across all 14 sessions; every repo's tests pass.
- 4 at once: ~26–27 t/s per session vs ~54 t/s solo, and each session takes roughly 1.3–1.5× as long.
  Matches node1's OpenCode load test (~28 t/s each at 4) and the original curl benchmark.
- Aider's one-shot prompts stay under 3K tokens, Goose's under 9K, so neither comes near 64K on small tasks.
- 4 agents at once ran on the 4 GB Pi without problems (Pi CPU/memory not measured).

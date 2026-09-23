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
| 5 Long session (16 turns) | not run | 🟡 16/16 turns ran, 0 errors, peak 37.7K, 23/23 tests, **but turn 14 silently made no edits** | ⏳ running |
| 6 Cold wake | not run | ✅ 7.5 s from sleep (warm disk) | ⏳ pending |
| 7 Shared load | not run | ⏳ pending | ⏳ pending |

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

### Goose: running

## Test 6: cold wake
Waited for `/props` → `is_sleeping: true`, then sent a trivial request.
- **Aider: 7.5 s** end to end, correct answer (warm-disk reload: model files still in the Mac's page cache).
- Goose: pending (needs the coder idle again for 5 min).

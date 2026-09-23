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
| 4 Multi-file rename | not run | not run | not run |
| 5 Long session (15–20 turns) | not run | not run | not run |
| 6 Cold wake | not run | not run | not run |
| 7 Shared load | not run | not run | not run |

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

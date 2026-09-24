# 03: Tests & results

Test plan is node1's ([`../node1-coder-cli/04-test-plan.md`](../node1-coder-cli/04-test-plan.md)), run from the Pi.
Throwaway repos under `~/harness-tests/` on the Pi. Pass/fail is checked independently (re-running
`uvx pytest -q` ourselves), not taken from the agent's own summary.

## Summary (2026-09-23)
| Test | Claude Code 2.1.280 (via `claude-mac`) | Aider 0.86.2 | Goose 1.52.0 |
|---|---|---|---|
| 1 Connects | ✅ | ✅ | ✅ |
| 2 Base prompt (tokens) | **18,109**, 21 tools | **611**, no tool schemas | **4,905**, 17 tools |
| 2 Left of the 64K slot | ~47K | ~65K | ~60K |
| 3 Tool loop (fizzbuzz + pytest) | ✅ 30 s, 4 turns, 2/2 pass | ✅ 16 s, 2/2 pass | ✅ 15 s, 2/2 pass |
| 4 Multi-file rename | ✅ 55 s, 8 requests / 17 tool calls, 0 leftovers, 4/4 | ✅ 25 s, 3 requests, 0 leftovers, 4/4 | ✅ 37 s, 18 requests / 21 tool calls, 0 leftovers, 4/4 |
| 5 Long session (16 turns) | ❌ defaults: **overflowed at turn 12**, turns 12–16 dead · 🟡 with `CLAUDE_CODE_MAX_CONTEXT_TOKENS=65536`: 16/16, peak 33.7K, but **`--db` ignored outside tests** | 🟡 default (`whole`) format: turn 14 silently made no edits · ✅ **`--edit-format diff`: 16/16, every feature works, peak 22.2K, ~12 min** | ✅ 16/16, all features work. Defaults: compaction request **51 tokens short of the limit**. **With `GOOSE_AUTO_COMPACT_THRESHOLD: 0.6`: peak 40.1K, ~28.7K headroom, ~11 min** |
| 6 Cold wake | ✅ 20.8 s (18K uncached prompt) | ✅ 7.5 s from sleep (warm disk) | ✅ 7.4 s from sleep (warm disk) |
| 7 Shared load | ✅ 1/2/4 sessions all pass; 4 at once 120–140 s, ~17 t/s each | ✅ 1/2/4 sessions all pass; 4 at once 36–60 s, ~26 t/s each | ✅ 1/2/4 sessions all pass; 4 at once 45–68 s, ~27 t/s each |

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

### Aider re-run with `--edit-format diff` (2026-09-23): 16/16 turns, every feature works
`AIDER_EXTRA="--edit-format diff" ./t5-long.sh aider diff`. Same 16 prompts. The script now also counts
**new git commits per turn** (Aider commits every edit it applies, so `+0` on a coding turn means nothing was
applied) and, at the end, which requested subcommands are missing from the CLI's `--help`.

| Turn | Wall | Tests (ours) | New commits | Peak prompt |
|---|---|---|---|---|
| 1 | 57 s | 3/3 | +3 | 6,968 |
| 2–6 | 21–30 s | 5 → 16 | +1 each | 4.8–6.9K |
| 7 (priority) | 92 s | 18/18 | +2 | 11,006 |
| 8 | 28 s | 18/18 | +1 | 7,814 |
| 9 (due date) | 100 s | 18/18 | +2 | 11,225 |
| 10 (overdue) | 93 s | 18/18 | +1 | 12,758 |
| 11 (summary question) | 21 s | 18/18 | **+0** (correct: no code asked for) | 16,777 |
| 12 (refactor) | 45 s | 18/18 | +1 | 16,777 |
| 13 (corrupt file) | 68 s | 19/19 | +1 | 16,958 |
| 14 (`search`) | 40 s | 19/19 | +1 | 21,105 |
| 15 (README) | 45 s | 19/19 | +2 | 21,105 |
| 16 (recall question) | 21 s | 19/19 | **+0** (correct) | 22,205 |

- **Every coding turn applied its edits**; subcommands missing at the end: **none**. Checked by hand: `add --priority
  --due`, list sorted high → normal → low, `overdue`, case-insensitive `search`, `done`, `delete`, bad-date error,
  corrupt-file error with exit 1.
- **Faster and smaller than the default format:** ~12 min total vs ~20, peak prompt 22.2K vs 37.7K, because replies
  are search/replace blocks instead of whole files.
- Fewer tests than Goose (19 vs 81): Aider writes what's asked and little more.
- Turn 16 recall: current signature `add(self, title, priority="normal", due_date=None)` and wrongly claimed that's
  the original. It then started running the tests although that turn didn't ask for it.
- 0 HTTP errors.

**Conclusion: use `--edit-format diff` with this model.** It fixes the silent no-op seen with `whole`, and it is faster.
One run each, so the no-op could in principle still occur. The commit check is cheap insurance for scripted use.

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

### Goose re-run with the compaction settings (2026-09-23): 16/16, peak 40.1K
`./t5-long.sh goose compact60` with `GOOSE_CONTEXT_LIMIT: 65536` and `GOOSE_AUTO_COMPACT_THRESHOLD: 0.6`.
(The script's `commits=+0` column is meaningless for Goose, which doesn't commit.)

| Turn | Wall | Tests (ours) | Peak prompt | Requests / tool calls |
|---|---|---|---|---|
| 1–6 | 6–37 s | 4 → 22 | 8.4–14.2K | 3–10 / 2–9 |
| 7 | 88 s | 29/29 | 22,431 | 13 / 12 |
| 8 | 9 s | 29/29 | 23,250 | 3 / 2 |
| 9 | 102 s | 35/35 | 30,018 | 18 / 17 |
| 10–12 | 10–49 s | 38/38 | 34.4–37.6K | 4–11 / 3–10 |
| 13 | 40 s | 40/40 | **40,101** (run peak) | 9 / 8 |
| 14 | 186 s | 46/46 | 36,832 (compaction request) → 6.4K | 26 / 24 |
| 15–16 | 5–28 s | 46/46 | 22.2–22.4K | 1–3 / 0–2 |

- **Compacted once, at the start of turn 14** ("Exceeded auto-compact threshold of 60%"): the prompt had reached
  ~40K (60 % of 65,536 = 39.3K). The summarising request was 36.8K, leaving **~28.7K of headroom** (vs 51 tokens with
  the defaults), and the session continued from 6.4K. Largest request of the run: 40.1K.
- **Faster: ~11 min vs ~24 min** with the defaults. Smaller prompts mean less prefill per request; run-to-run
  variation is also large for this model, so treat the speed-up as indicative.
- 0 HTTP errors, 0 malformed tool calls (~115 tool calls). Subcommands missing: none. Checked by hand: `add --priority
  --due`, list sorted high → normal → low, `overdue`, case-insensitive `search`, `done`, `delete`, corrupt-file error
  with exit 1 all work.
- **One quality regression:** an invalid date from the CLI (`add X --due 2020-13-45`) crashes with a traceback. The
  default-settings Goose build and the Aider `diff` build both print a one-line error and exit 1. Not a spec failure
  (turn 9 only asked the store to raise `ValueError`; the clean-error requirement in turn 13 was for corrupt files),
  but it shows the two runs made different judgement calls.
- 46 tests (vs 81 in the first Goose run). Fewer tests is plausibly the price of a shorter history after compaction,
  but with one run each that is a guess.
- Turn 16 recall: answered from the compaction summary and gave the **current** signature
  (`add(title, priority="normal", due_date=None)`) as the "first request". Worse than the first run, which noted the
  original was `add(title)`, because early detail is exactly what compaction throws away.

**Conclusion: keep `GOOSE_AUTO_COMPACT_THRESHOLD: 0.6`.** It turns a near-overflow into ~29K of headroom and cost
nothing measurable in delivered features. The trade-off is weaker recall of early turns after compaction.

### Aider vs Goose on the same 16 turns
| | Aider | Goose |
|---|---|---|
| Total time | ~20 min (`diff`: ~12 min) | ~24 min (threshold 0.6: ~11 min) |
| Peak prompt | 37.7K (`diff`: 22.2K), no compaction needed | 65.5K near miss (threshold 0.6: 40.1K) |
| Tests at the end | 23 (`diff`: 19) | 81 (threshold 0.6: 46) |
| Features actually working | all but `search` (silent no-op); **all with `--edit-format diff`** | all |
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

## Claude Code: tests 4–7 (2026-09-23)
Run through the same scripts: `agent claude` = `claude-mac -p … --dangerously-skip-permissions`, `-c` to continue the
session on later turns. `logproxy.py` was extended to parse Anthropic `/v1/messages` streams (usage from
`message_start`, tool calls from `tool_use` blocks) so Claude Code gets the same per-request numbers as the others.

### Test 4: rename: ✅
55 s, 8 requests, 17 tool calls (Bash grep → Read×5 → Edit×7 → Bash tests), 0 leftovers, 5 files, 4/4 tests.
Prompt 18.2K → 21.7K. Slowest of the three (Aider 25 s, Goose 37 s) because every request carries ~18K of
system prompt and tool schemas.

### Test 5: 16 turns, default settings: ❌ context overflow at turn 12
| Turn | Wall | Tests (ours) | Peak prompt | Requests / tool calls |
|---|---|---|---|---|
| 1–6 | 14–42 s | 4 → 21 | 19.5–28.4K | 4–5 / 3–6 |
| 7 | 105 s | 25/25 | 41,539 | 21 / 20 |
| 8 | 31 s | 26/26 | 44,878 | 6 / 5 |
| 9 | 108 s | 31/31 | 55,890 | 19 / 18 |
| 10 | 69 s | 37/37 | 64,210 | 12 / 11 |
| 11 | 10 s | 37/37 | 64,836 | 3 / 2 |
| 12 | 3 s, **exit 1** | 37/37 | 65,056 then **400** | 2 / 1 |
| 13–16 | 1–2 s each, **exit 1** | 37/37 | **400** on the first request | 1 / 0 |

`400 request (66,110 tokens) exceeds the available context size (65536 tokens)`. Claude Code never compacted: it
assumes a **200K** window for a model it doesn't know, so its auto-compact threshold was far above 64K. From turn 12 every
request was over the limit, so the session was dead: the refactor, corrupt-file handling, `search` and the README were
never done (final: `storage.py`, `README.md` and `search` missing). Same failure as Qwen Code on node1 before its
`contextWindowSize` fix. Turns 1–11 were clean: 0 malformed tool calls in ~80.

Claude Code's own stderr names the fix: *"set CLAUDE_CODE_MAX_CONTEXT_TOKENS to its real window"*. Now set to 65536
in `claude-mac` ([`scripts/claude-mac`](scripts/claude-mac)); re-run below.

### Test 6: cold wake: ✅ 20.8 s
Correct answer, no timeout. Slower than Aider/Goose (~7.5 s) because the first request after the reload has to
process Claude Code's ~18K-token base prompt from scratch.

### Test 7: shared load: ✅ all 7 sessions pass
| Sessions | Wall per session | Tests (ours) | Busy slots (max) | Per-slot decode | Requests / tool calls |
|---|---|---|---|---|---|
| 1 | 44 s | 19/19 | 1 | 50 t/s | 4 / 4 |
| 2 | 85 s, 96 s | 16/16, 16/16 | 2 | 21 t/s | 12 / 12 |
| 4 | 120–140 s | 15–18, all pass | 4 | 17 t/s | 20 / 20 |

0 errors, 0 malformed tool calls. **It scales worst of the three:** at 4 sessions each takes ~3× as long as solo (Aider
and Goose ~1.3–1.5×). Likely cause: every request carries ~19–21K of prompt, and 4 sessions prefilling that at once compete for the same
GPU (not measured separately).

### Test 5 re-run with `CLAUDE_CODE_MAX_CONTEXT_TOKENS=65536`: 🟡 no overflow, but a broken CLI
`./t5-long.sh claude ctx64k` after adding the variable to `claude-mac`.

| Turn | Wall | Tests (ours) | Peak prompt | Requests / tool calls |
|---|---|---|---|---|
| 1–4 | 15–54 s | 4 → 11 | 21.8–26.2K | 4–8 / 3–9 |
| 5 | 124 s | 11/11 | 32,499 → compacted → 21.3K | 15 / 13 |
| 6–9 | 36–68 s | 20 → 22 | 25.7–33.6K | 4–16 / 3–15 |
| 10 | 74 s | 22/22 | 33,719 → compacted → 21.6K | 11 / 9 |
| 11–12 | 15–29 s | 22/22 | 27.0–29.7K | 3–5 / 4–5 |
| 13 | 120 s | 24/24 | 31,120 | 21 / 20 |
| 14–16 | 4–60 s | 24/24 | 28.6–32.1K | 1–8 / 0–6 |

- **The overflow is fixed.** Claude Code now compacts silently at ~32–34K (about half the slot) back to ~21K, several
  times in the session. Peak 33.7K; 0 HTTP errors; 0 malformed tool calls (~100). ~13 min total.
- All 6 subcommands exist; `storage.py` refactor and a 118-line README done. 24 tests, all pass.
- **But the CLI is broken for real use: `--db` is ignored from the command line.** `main(argv=None)` only scans
  `argv` for `--db` when it is passed explicitly, which is how the tests call it. Run as a program, it always
  uses `./todo.json`. The tests pass; a user's `--db` silently does nothing. This is the "tests pass, CLI broken" failure
  that black-box checking exists to catch. Found only by driving the CLI by hand (fresh `--db` file showed ids 3–5 and
  someone else's tasks). The Aider `diff` build and both Goose builds honour `--db`.
- An invalid `--due` date crashes with a traceback (as in the second Goose build).
- Turn 16 recall: said it had no memory of the first request (true after compaction) and listed the current methods.
  The most honest answer of the lot, but no recall.

**Conclusion:** `CLAUDE_CODE_MAX_CONTEXT_TOKENS=65536` is required for Claude Code on this server (now in `claude-mac`).
With it Claude Code completes long sessions, but it produced the only functionally broken CLI among the final builds,
and it scales worst under load. One run each, so treat the quality difference as indicative.

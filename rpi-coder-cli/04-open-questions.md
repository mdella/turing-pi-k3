# 04: Open questions

## 1. Claude Code doesn't know the slot is 64K
Claude Code sizes its auto-compaction for a 200K window, and its base prompt is already 18K. In a long session
it will probably send a request > 65,536 tokens and get a 400 from llama-server. That's exactly what happened to Qwen Code in node1
test 5 before its `contextWindowSize` fix. Test 5 will show whether that happens; the fix, if needed, is a
Claude Code compaction setting (to be found and verified), not more slot memory. Aider already has the real
window (`~/.aider.model.metadata.json`); Goose's handling is untested.

## 2. Which harness to standardise on for the Pi agent: Goose (provisional, 2026-09-23)
After tests 1–7 (see [03](03-test-results.md)):
- **Goose** delivered every requested feature in the 16-turn session (81 tests), handles tool calling cleanly
  (~200 tool calls across all tests, 0 malformed) and can load MCP tools. Default for autonomous or scripted work.
  Needs the compaction settings in [02](02-install-config.md): near miss in test 5 with defaults; re-run with them
  peaked at 40.1K with ~29K headroom.
- **Aider** is faster on small edits and its prompts are tiny (never above 38K even after 16 turns), but in scripted use
  in its default `whole` edit format it **silently applied nothing and still exited 0** (test 5, turn 14).
  Re-run with **`--edit-format diff`: all 16 turns applied, every feature works, ~12 min, peak 22K**. `edit-format: diff` is now the Pi default. With it, Aider is
  a strong option for coding tasks too; still check for a new commit after each scripted run.
- **Claude Code** only passed tests 1–3; its 18K base prompt and 200K assumption make it the riskiest on 64K slots.

## 2a. Exit codes can't be trusted by a scripted agent
Both harnesses returned 0 when nothing useful happened: Aider after a no-op turn, Goose after
`Network error: Could not connect` (seen when the proxy wasn't running). A Pi agent that runs them from cron must
check results itself (git commits, test run, output text), not just `$?`.

## 3. No authentication on :8080 / :11434
Same as node1 05 §2: any netbird peer or LAN host can use the coder. The Pi adds one more client on a remote
site. `--api-key` on llama-server would need the key in all three configs here (`OPENAI_API_KEY`,
`openai-api-key`, `ANTHROPIC_AUTH_TOKEN`).

## 4. Shared capacity
The Pi competes for the same 4 slots as node1 users and Mac-local sessions. An unattended Pi agent should run
one session at a time.

# 04: Open questions

## 1. Claude Code doesn't know the slot is 64K
Claude Code sizes its auto-compaction for a 200K window, and its base prompt is already 18K. In a long session
it will probably send a request > 65,536 tokens and get a 400 from llama-server. That's exactly what happened to Qwen Code in node1
test 5 before its `contextWindowSize` fix. Test 5 will show whether that happens; the fix, if needed, is a
Claude Code compaction setting (to be found and verified), not more slot memory. Aider already has the real
window (`~/.aider.model.metadata.json`); Goose's handling is untested.

## 2. Which harness to standardise on for the Pi agent
Only short tasks so far. Aider (tiny prompt, git-native, no tool calling) and Goose (small prompt, MCP-native,
general-purpose) both look like better fits for a 64K slot than Claude Code. Goose can also load MCP servers
such as [`../mac-studio-flux2/flux2_mcp.py`](../mac-studio-flux2/flux2_mcp.py). Decide after tests 4–7.

## 3. No authentication on :8080 / :11434
Same as node1 05 §2: any netbird peer or LAN host can use the coder. The Pi adds one more client on a remote
site. `--api-key` on llama-server would need the key in all three configs here (`OPENAI_API_KEY`,
`openai-api-key`, `ANTHROPIC_AUTH_TOKEN`).

## 4. Shared capacity
The Pi competes for the same 4 slots as node1 users and Mac-local sessions. An unattended Pi agent should run
one session at a time.

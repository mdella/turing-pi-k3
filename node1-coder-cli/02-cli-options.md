# 02 — Choosing the CLI

All candidates speak OpenAI-compatible APIs natively, so they connect straight to `:8080/v1` with no
translation proxy. (Claude Code would need a proxy, since it speaks the Anthropic Messages API, and it is tuned for Claude — ruled out.)

node1 has Node 22 / npm 10 and Python 3.12; **no pipx or uv yet**.

| CLI | Install on node1 | Why consider it | Watch out for |
|---|---|---|---|
| **Qwen Code** | npm (`@qwen-code/qwen-code`) | Built by the Qwen team for Qwen3-Coder; agentic (sub-agents, MCP, memory) | Its system prompt + tool schemas may be large relative to our 32K slot (see 05) |
| **OpenCode** | npm | Most popular open "Claude-Code-style" TUI, model-agnostic | Provider config via `opencode.json`; same context question |
| **Aider** | Python (needs pipx/uv or a venv) | Mature, git-aware, diff-based edits; small prompts | Less autonomous (pair-programmer, not a full agent) |

## Decision
1. **Trial Qwen Code first** — best match for this exact model's tool-calling style.
2. **OpenCode second** if Qwen Code's prompt doesn't fit or its UX isn't liked.
3. **Aider as the baseline** — lightest prompts, useful to tell "model problem" from "CLI problem".

Decide the winner using the test plan in [04](04-test-plan.md).

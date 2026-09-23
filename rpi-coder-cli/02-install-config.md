# 02: Install & configure (Pi, user `mdella`)

Everything is per-user in `~/.local/bin`; nothing system-wide except `git` from apt.

## uv 0.12.18
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh     # adds ~/.local/bin to PATH in .bashrc/.profile
```

## Shared endpoint settings: `~/.config/local-llm.env` (sourced from `.bashrc`)
```bash
export LOCAL_LLM_BASE=http://100.101.193.15:8080
export LOCAL_LLM_MODEL=qwen3-coder-next
export OPENAI_API_KEY=local        # dummy: llama-server has no auth, but OpenAI-style clients insist on a key
```

## Claude Code 2.1.280
```bash
curl -fsSL https://claude.ai/install.sh | bash
```
No login needed when pointed at the local server. llama-server implements `/v1/messages` itself:
```bash
ANTHROPIC_BASE_URL=http://100.101.193.15:8080 ANTHROPIC_AUTH_TOKEN=local ANTHROPIC_API_KEY= \
ANTHROPIC_DEFAULT_HAIKU_MODEL=qwen3-coder-next ANTHROPIC_SMALL_FAST_MODEL=qwen3-coder-next \
claude --model qwen3-coder-next
```
- The `HAIKU`/`SMALL_FAST` overrides route Claude Code's background housekeeping calls to the same model.
- Harmless stderr noise: `[claude-code:unrecognized_model]`.
- Claude Code believes the window is **200K**; the slot is **64K**. See [04](04-open-questions.md) §1.
- No wrapper script yet; the env vars are typed per invocation.

## Aider 0.86.2
```bash
sudo apt-get install -y git              # Aider is git-centric; the Pi had no git
uv tool install --python 3.12 aider-chat
```
`~/.aider.conf.yml`:
```yaml
model: openai/qwen3-coder-next
openai-api-base: http://100.101.193.15:8080/v1
openai-api-key: local
model-metadata-file: ~/.aider.model.metadata.json
analytics-disable: true
check-update: false
show-model-warnings: false
```
`~/.aider.model.metadata.json` tells Aider (via litellm) the real window, so it doesn't guess:
```json
{ "openai/qwen3-coder-next": { "max_input_tokens": 65536, "max_output_tokens": 8192,
  "input_cost_per_token": 0, "output_cost_per_token": 0,
  "litellm_provider": "openai", "mode": "chat" } }
```

## Goose 1.52.0
```bash
curl -fsSL https://github.com/block/goose/releases/download/stable/download_cli.sh | CONFIGURE=false bash
```
`~/.config/goose/config.yaml` (API key comes from `OPENAI_API_KEY` in `local-llm.env`):
```yaml
GOOSE_PROVIDER: openai
GOOSE_MODEL: qwen3-coder-next
OPENAI_HOST: http://100.101.193.15:8080
OPENAI_BASE_PATH: v1/chat/completions
GOOSE_TELEMETRY_ENABLED: false
extensions:
  developer:
    enabled: true
    name: developer
    type: builtin
    timeout: 300
```
Added after test 5 (see [03](03-test-results.md)): the slot is 64K and Goose only checks the compaction threshold
between turns, so compact earlier:
```yaml
GOOSE_CONTEXT_LIMIT: 65536
GOOSE_AUTO_COMPACT_THRESHOLD: 0.6
```
Non-interactive use: `goose run --no-session -t "…"`.

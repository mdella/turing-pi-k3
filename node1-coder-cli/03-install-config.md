# 03 — Install & configure on node1

Status: ⏳ not started. Config keys below are from each project's docs at the time of writing —
**confirm against the installed version's README/`--help`** when doing the install, and record what actually worked here.

Common values:
```
BASE_URL = http://100.101.193.15:8080/v1
MODEL    = qwen3-coder-next
API_KEY  = none needed; use any placeholder (e.g. "local") if the CLI insists
```

## Qwen Code (first trial)
```bash
npm install -g @qwen-code/qwen-code
export OPENAI_BASE_URL=http://100.101.193.15:8080/v1
export OPENAI_API_KEY=local
export OPENAI_MODEL=qwen3-coder-next
qwen            # run inside the project directory
```
Persist the three exports in `~/.bashrc` (or a small wrapper script) once it works.

## OpenCode (second trial)
`~/.config/opencode/opencode.json`:
```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "mac-studio": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Mac Studio coder",
      "options": { "baseURL": "http://100.101.193.15:8080/v1" },
      "models": { "qwen3-coder-next": { "name": "Qwen3 Coder Next" } }
    }
  }
}
```

## Aider (baseline)
```bash
python3 -m venv ~/.venvs/aider && ~/.venvs/aider/bin/pip install aider-chat
~/.venvs/aider/bin/aider --model openai/qwen3-coder-next \
  --openai-api-base http://100.101.193.15:8080/v1 --openai-api-key local
```

## Record here after install
| CLI | Version | Worked as written? | Changes needed |
|---|---|---|---|
| Qwen Code | | | |
| OpenCode | | | |
| Aider | | | |

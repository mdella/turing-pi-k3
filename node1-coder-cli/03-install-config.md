# 03 — Install & configure on node1

Status: 🟡 Qwen Code installed 2026-09-23 (OpenCode, Aider not yet). Config keys below are from each project's docs at the time of writing —
**confirm against the installed version's README/`--help`** when doing the install, and record what actually worked here.

Common values:
```
BASE_URL = http://100.101.193.15:8080/v1
MODEL    = qwen3-coder-next
API_KEY  = none needed; use any placeholder (e.g. "local") if the CLI insists
```

## Qwen Code (first trial)
npm's global prefix on node1 is `/usr` (needs sudo), so install to the user prefix instead —
`~/.local/bin` is already on PATH:
```bash
npm install -g --prefix ~/.local @qwen-code/qwen-code
# bundled ripgrep ships without +x (EACCES → falls back to slow built-in grep):
chmod +x ~/.local/lib/node_modules/@qwen-code/qwen-code/vendor/ripgrep/arm64-linux/rg
export OPENAI_BASE_URL=http://100.101.193.15:8080/v1
export OPENAI_API_KEY=local
export OPENAI_MODEL=qwen3-coder-next
qwen            # run inside the project directory
```
Persist the three exports in `~/.bashrc` (or a small wrapper script) once it works.

**Required** user-level `~/.qwen/settings.json` (in place on node1 since 2026-09-23):
```json
{
  "model": { "generationConfig": { "contextWindowSize": 65536 } },
  "memory": { "enableManagedAutoMemory": false, "enableManagedAutoDream": false, "enableAutoSkill": false },
  "general": { "outputLanguage": "English" }
}
```
- `contextWindowSize` — **must match the server's per-slot n_ctx** (65536 now). Without it Qwen Code guesses the
  window from the model name, never auto-compacts, and the session dies with `400 … exceeds the available context size`
  (test 5, run 1). Update it whenever the plist's `-c / --parallel` changes.
- `memory.*` — stops a ~10K-token background request after every turn that holds a second shared slot (test 2).
- `outputLanguage` — with `auto`, the model drifted into Chinese for summaries, docstrings and test data (tests 4, 5, 7).
  **Gotcha:** the setting is compiled into `~/.qwen/output-language.md` (loaded as context), and that file is only
  written when it doesn't exist yet — changing the setting later is silently ignored. After changing it:
  `rm ~/.qwen/output-language.md` (or use `/language` interactively). Verified: the file now says
  "You MUST always respond in **English**" and the concurrent runs that had drifted came back 100% English.

## OpenCode (second trial) — installed 2026-09-23, v1.18.32
```bash
npm install -g --prefix ~/.local opencode-ai
```
`~/.config/opencode/opencode.json` (in place on node1):
```json
{
  "$schema": "https://opencode.ai/config.json",
  "autoupdate": false,
  "share": "disabled",
  "model": "mac-studio/qwen3-coder-next",
  "provider": {
    "mac-studio": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Mac Studio coder",
      "options": { "baseURL": "http://100.101.193.15:8080/v1", "apiKey": "local" },
      "models": {
        "qwen3-coder-next": {
          "name": "Qwen3 Coder Next",
          "tool_call": true,
          "limit": { "context": 65536, "output": 8192 }
        }
      }
    }
  }
}
```
- `limit.context` **must match the server's per-slot n_ctx** (same lesson as Qwen Code). Auto-compaction fires at
  context − output (≈57K here); `output` is also sent as `max_tokens`.
- `share: disabled` keeps sessions from being uploaded to opencode.ai; `autoupdate: false` keeps the version pinned.
- Headless use: `opencode run --auto "…"` (`--continue` to resume). **Always redirect stdin (`</dev/null`) in scripts** —
  with an open stdin pipe `opencode run` waits for input forever before sending anything.
- No request-logging flag; tests used a small logging proxy (`127.0.0.1:18080` → Mac) — config points at the Mac directly.

## Aider (baseline)
```bash
python3 -m venv ~/.venvs/aider && ~/.venvs/aider/bin/pip install aider-chat
~/.venvs/aider/bin/aider --model openai/qwen3-coder-next \
  --openai-api-base http://100.101.193.15:8080/v1 --openai-api-key local
```

## Record here after install
| CLI | Version | Worked as written? | Changes needed |
|---|---|---|---|
| Qwen Code | 0.24.4 | Env vars work; **settings file required** for long sessions | `--prefix ~/.local`; `chmod +x` bundled rg; `~/.qwen/settings.json` above; exports in `~/.bashrc` |
| OpenCode | 1.18.32 | Yes, with `limit` added | `--prefix ~/.local`; `limit.context/output`; `apiKey` placeholder; `</dev/null` for scripted runs |
| Aider | | | |

# 06 — How to use the coding CLI on node1

A terminal coding agent (like Claude Code, but using the Mac Studio's local model) runs on **k3-node1**.
You talk to it in plain English inside a project folder; it reads files, edits code and runs commands for you.

## What you need

| Thing | Where / what |
|---|---|
| A terminal on node1 | `ssh ubuntu@192.168.4.101` (node1 is the only machine that can reach the coder, over netbird) |
| The app | **OpenCode** (recommended) → command `opencode`. Alternative: **Qwen Code** → command `qwen`. Both already installed in `~/.local/bin` |
| Settings | Already in place for the `ubuntu` user — see [Settings files](#settings-files). Nothing to set up to start |
| The model | `qwen3-coder-next` on the Mac Studio (`http://100.101.193.15:8080/v1`). Shared by everyone, no API key |

## Quick start

```bash
ssh ubuntu@192.168.4.101
cd ~/my-project            # always start inside the project folder — the agent works on the current directory
git status                 # use git, so you can review/undo what the agent changed (git diff, git checkout .)
opencode                   # opens the full-screen app
```

Then type what you want, e.g. *"Add a --verbose flag to cli.py and a test for it, then run the tests."*

- It **asks permission** before editing files or running shell commands — read the request, then approve or reject.
- **Tab** switches between the *build* agent (makes changes) and the *plan* agent (read-only: analyses and proposes).
- Type **`/`** to see the commands (new session, list sessions, compact, exit, …). **Ctrl-C** interrupts/quits.
- Resume the last conversation later: `opencode --continue` (or pick one from the sessions list inside the app).

### Qwen Code instead
```bash
cd ~/my-project
qwen                       # full-screen app; type /help for commands, /quit to exit
qwen --continue            # resume the last session in this folder
```
Use it for very long sessions where you'll ask about work from much earlier — it keeps early history better (see [04](04-test-plan.md)).

## One-shot / scripted use

Run a single request without the full-screen app (good for scripts, cron, quick jobs):

```bash
cd ~/my-project
opencode run "Explain what src/main.py does in 5 bullets" </dev/null
opencode run --continue "Now add type hints to it" </dev/null     # follow-up in the same session
qwen "Explain what src/main.py does in 5 bullets"                  # Qwen Code equivalent
qwen --continue "Now add type hints to it"
```

- **`</dev/null` is required for `opencode run` in scripts** — without it, it can wait for input forever and send nothing.
- In one-shot mode there is no one to approve edits, so edit/shell tools are withheld unless you allow them:
  `opencode run --auto …` or `qwen --approval-mode yolo …` auto-approve **everything** (file writes *and* shell commands).
  Only use these in a git repo or throwaway folder you're happy to lose.
- `qwen` needs the three `OPENAI_*` variables from `~/.bashrc`. A login shell has them; cron/systemd does not — set them
  in the job (see below) or you'll get *"No auth type is selected"*.

## What to expect

| Situation | Typical |
|---|---|
| Simple question | 5–15 s |
| Small task (write a module + tests, run them) | 25–60 s alone, 70–90 s when 4 people are busy |
| First request after 5+ min of nobody using it | +3 s (model reloads) up to ~50 s if the Mac swapped it out; the app just waits |
| Speed per person | ~59 tokens/s alone → ~44 with 2 busy → ~28 with 4 busy |
| Capacity | **4 requests at once** for everyone combined; a 5th waits for a free slot |
| Memory | 64K tokens per conversation; older history is auto-summarised ("compacted") when it fills |

## Settings files

These make the apps work with *this* server. Already done for `ubuntu`; copy them for any other user account.

**OpenCode** — `~/.config/opencode/opencode.json`
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

**Qwen Code** — `~/.qwen/settings.json`, plus the environment variables in `~/.bashrc`
```json
{
  "model": { "generationConfig": { "contextWindowSize": 65536 } },
  "memory": { "enableManagedAutoMemory": false, "enableManagedAutoDream": false, "enableAutoSkill": false },
  "general": { "outputLanguage": "English" }
}
```
```bash
export OPENAI_BASE_URL=http://100.101.193.15:8080/v1
export OPENAI_API_KEY=local
export OPENAI_MODEL=qwen3-coder-next
```

The one setting that matters most: **the context size (65536) must match the server's per-slot context.** If the Mac's
llama-server `-c` / `--parallel` ever change, update `limit.context` (OpenCode) and `contextWindowSize` (Qwen Code).
Why each setting exists: [03](03-install-config.md).

### Installing for a new user account
```bash
npm install -g --prefix ~/.local opencode-ai            # OpenCode
npm install -g --prefix ~/.local @qwen-code/qwen-code   # Qwen Code (optional)
chmod +x ~/.local/lib/node_modules/@qwen-code/qwen-code/vendor/ripgrep/arm64-linux/rg
# then create the settings files above; make sure ~/.local/bin is on PATH
```

## Is the coder up?

```bash
curl -s http://100.101.193.15:8080/health                     # {"status":"ok"}
curl -s http://100.101.193.15:8080/props | python3 -c 'import json,sys;print("sleeping:",json.load(sys.stdin)["is_sleeping"])'
curl -s http://100.101.193.15:8080/slots | python3 -c 'import json,sys;print("busy slots:",sum(s["is_processing"] for s in json.load(sys.stdin)),"of 4")'
```

## Troubleshooting

| Symptom | Cause → fix |
|---|---|
| `opencode run` in a script sits forever, nothing happens | stdin left open → add `</dev/null` |
| `400 … exceeds the available context size (65536 tokens)` and every later message fails | App's context setting missing/too big → fix the setting above, start a **new** session (the broken one can't recover) |
| `qwen`: *No auth type is selected* | `OPENAI_*` variables not set in this shell (cron, `sudo`, non-login shell) → export them |
| Qwen Code replies in Chinese | `rm ~/.qwen/output-language.md` then restart `qwen` (it rebuilds the file from `outputLanguage`) |
| *Connection refused* / *fetch failed* | Coder stopped on the Mac (someone ran `ai-mem big`; restore with `ai-mem coder`), or netbird down on node1 (`netbird status`) |
| First reply very slow, later ones fine | Model was asleep (idle > 5 min) and is reloading — normal |
| Everything slow | Other people are using it — check busy slots above |
| Agent did something unwanted | `git diff` to review, `git checkout .` / `git clean -fd` to undo (that's why you start in a git repo) |

## Re-running the evaluation tests (optional)

How the results in [04](04-test-plan.md) were produced, so they can be repeated (e.g. after an upgrade).
Use a throwaway folder: `mkdir -p ~/cli-trial/x && cd ~/cli-trial/x && git init`.

| Test | Command (OpenCode; Qwen Code: `qwen --approval-mode yolo "…"`) |
|---|---|
| 1–2 connect / prompt size | `opencode run --auto "What is 17*23? Answer with just the number." </dev/null` |
| 3 tool loop | `opencode run --auto "Create fizzbuzz.py … write test_fizzbuzz.py using unittest … run the tests and fix any error until they pass." </dev/null` |
| 4 multi-file edit | copy a small repo with a function used in several files, then `"Rename the function X to Y everywhere … run python3 -m unittest"` |
| 5 long session | 16 follow-up requests building one project, each with `opencode run --auto --continue "…" </dev/null` |
| 6 cold wake | wait until `sleeping: True` (check above), then send any request and time it |
| 7 shared load | start 2–4 of the same one-shot command at once in separate folders (`… &` then `wait`) |

Measuring tools in [`scripts/`](scripts/):
- **Prompt size** — Qwen Code: add `--openai-logging --openai-logging-dir ./logs`; each JSON file has `response.usage.prompt_tokens`.
  OpenCode has no such flag: run `PROXY_LOG=~/proxy.jsonl python3 scripts/logproxy.py &`, temporarily set `baseURL` to
  `http://127.0.0.1:18080/v1` in `opencode.json`, run the test, then **set it back** and stop the proxy.
- **Speed under load** — `python3 scripts/slot-poll.py ~/poll.jsonl &` during the test; each line has the busy slots and
  per-slot tokens/s. Stop it with `kill %1` afterwards.

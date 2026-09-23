# 05: How to use the coding agents on the Pi

Three terminal agents run on the Raspberry Pi (`rpi-sr-101`). None of them run a model on the Pi: they all
send their requests to **qwen3-coder-next** on the Mac Studio over netbird. You talk to them in plain English
inside a project folder; they read files, edit code and (Goose, Claude Code) run commands.

| Agent | Command | Pick it when |
|---|---|---|
| **Aider** | `aider` | Editing code in a git repo. Every change becomes a git commit you can review or `/undo`. Smallest prompts (~0.6K tokens), so the 64K context lasts longest. You choose which files it may edit. |
| **Goose** | `goose` | General tasks: it runs shell commands, reads and writes files, and can use MCP tools (e.g. the FLUX.2 image tool). Small prompt (~4.9K). |
| **Claude Code** | `claude-mac` | You want the Claude Code interface. Heaviest prompt (~18K), and it doesn't know the context is only 64K (see [04](04-open-questions.md) §1), so keep sessions short. |

## What you need

| Thing | Where / what |
|---|---|
| A terminal on the Pi | `ssh mdella@rpi-sr-101-77-5.cstone.to` |
| The apps | Already installed in `~/.local/bin` for `mdella`: `aider`, `goose`, `claude`, `claude-mac`, `uv` |
| Settings | Already in place, see [Settings files](#settings-files). Nothing to set up to start |
| The model | `qwen3-coder-next` at `http://100.101.193.15:8080`. Shared with everyone (node1, the Mac), no API key |

Always work **inside a git repo** (`git init` if needed), so anything an agent does can be reviewed with
`git diff` and undone with `git checkout .` / `git clean -fd`.

## Aider

```bash
cd ~/my-project
aider                          # opens the chat; no files are editable yet
aider src/app.py tests/        # start with these files already added
```
Inside the chat:

| Command | Does |
|---|---|
| `/add <file>` / `/drop <file>` | Let it edit a file / take it away. **Aider only edits files you've added**; it can see the rest through its repo map. |
| `/ask <question>` | Question only, no edits |
| `/run <cmd>` | Run a shell command and optionally share the output with the model |
| `/test` | Run the test command and ask it to fix failures |
| `/undo` | Revert its last commit |
| `/diff` | Show what the last change did |
| `/clear` | Forget the conversation (files stay added) |
| `/exit` or Ctrl-D | Quit |

Useful start-up options:
```bash
aider --test-cmd "python3 -m unittest" --auto-test     # run tests after every edit and fix failures
aider --no-auto-commits                                # stage changes but don't commit them
aider --restore-chat-history                           # continue the last conversation in this repo
```

One-shot (scripts, cron):
```bash
aider --yes-always --message "Add type hints to utils.py" utils.py
```
`--yes-always` approves everything, including creating files. Only use it in a git repo.

## Goose

```bash
cd ~/my-project
goose session                  # interactive; type /help for commands, /exit to quit
goose session -r               # resume the most recent session
goose session -n myjob         # named session; resume it later with: goose session -n myjob -r
```
Goose runs shell commands and edits files **without asking** by default (`GOOSE_MODE: auto`). To be asked
first, add `GOOSE_MODE: approve` (or `smart_approve`: ask only for risky actions) to `~/.config/goose/config.yaml`,
or choose it in `goose configure`. Otherwise work in a git repo you can reset.

One-shot (scripts, cron):
```bash
goose run --no-session -t "Summarise what this repo does in 5 bullets"
goose run -n nightly -t "Run the tests and fix any failures"          # keeps a named session
goose run -n nightly -r -t "Now update the README for those changes"  # continues it
```

### Adding tools (MCP servers)
Goose can use any MCP server. For example, to let it generate images on the Mac's ComfyUI (FLUX.2):
```bash
curl -fsSL https://raw.githubusercontent.com/mdella/turing-pi-k3/main/mac-studio-flux2/flux2_mcp.py -o ~/flux2_mcp.py
COMFYUI_URL=http://100.101.193.15:8199 \
  goose session --with-extension "uv run --with mcp $HOME/flux2_mcp.py"
```
(or add it permanently with `goose configure` → *Add Extension* → *Command-line Extension*).

## Claude Code (`claude-mac`)

```bash
cd ~/my-project
claude-mac                     # same interface as normal Claude Code
claude-mac -c                  # continue the last session in this folder
claude-mac -p "Explain what src/main.py does"                  # one-shot, prints the answer
claude-mac -p "Fix the failing test" --dangerously-skip-permissions   # one-shot that may edit/run (git repo only)
```
`claude-mac` is a small wrapper that points Claude Code at the Mac and checks the coder is up first.
Plain `claude` is untouched and would try to use the Anthropic cloud (needs a login).

- Keep sessions short, or run `/compact` yourself when a session gets long: Claude Code thinks it has 200K of
  context, but the server gives it 64K, and it starts at 18K.
- If you see `400 … exceeds the available context size`, start a new session (`/clear` or restart).

## What to expect (measured from the Pi, see [03](03-test-results.md))

| Situation | Typical |
|---|---|
| Simple question | Aider/Goose 1–5 s; Claude Code ~18 s for the first request of a session, faster after |
| Small task (module + tests, run them) | 15–30 s |
| Rename across 5 files + tests | Aider 25 s, Goose 37 s |
| First request after 5+ min of nobody using the coder | +3–8 s (model reloads), up to ~50 s if the Mac swapped it out |
| Several agents at once | ~54 t/s alone → ~34–43 with 2 busy → ~26–27 with 4 busy; tasks take ~1.3–1.5× as long |
| Capacity | **4 requests at once** for everyone combined (Pi, node1, Mac); a 5th waits |
| Context | 64K tokens per conversation |

## Settings files

Why each one exists: [02](02-install-config.md).

| File | For |
|---|---|
| `~/.config/local-llm.env` (sourced by `~/.bashrc`) | `LOCAL_LLM_BASE`, `LOCAL_LLM_MODEL`, dummy `OPENAI_API_KEY=local` |
| `~/.aider.conf.yml` | model `openai/qwen3-coder-next`, `openai-api-base: http://100.101.193.15:8080/v1` |
| `~/.aider.model.metadata.json` | tells Aider the context is 65,536 tokens |
| `~/.config/goose/config.yaml` | provider `openai`, `OPENAI_HOST: http://100.101.193.15:8080`, model, developer extension, `GOOSE_CONTEXT_LIMIT: 65536`, `GOOSE_AUTO_COMPACT_THRESHOLD: 0.6` |
| `~/.local/bin/claude-mac` | Claude Code wrapper ([`scripts/claude-mac`](scripts/claude-mac)) |

**If the Mac's llama-server context ever changes** (`-c` / `--parallel` in its plist), update
`max_input_tokens` in `~/.aider.model.metadata.json` and `GOOSE_CONTEXT_LIMIT` in the Goose config.

### Scripts and cron
Non-login shells (cron, systemd) don't read `~/.bashrc`. Start jobs with:
```bash
export PATH="$HOME/.local/bin:$PATH"; . ~/.config/local-llm.env
```
Goose needs `OPENAI_API_KEY` from that file; Aider and `claude-mac` have their settings in their own files.

## Is the coder up?
```bash
curl -s http://100.101.193.15:8080/health                     # {"status":"ok"}
curl -s http://100.101.193.15:8080/props | python3 -c 'import json,sys;print("sleeping:",json.load(sys.stdin)["is_sleeping"])'
curl -s http://100.101.193.15:8080/slots | python3 -c 'import json,sys;print("busy slots:",sum(s["is_processing"] for s in json.load(sys.stdin)),"of 4")'
netbird status | head -5                                      # is the Pi's netbird link up?
```

## Troubleshooting

| Symptom | Cause → fix |
|---|---|
| *Connection refused* / `claude-mac: coder not reachable` | Coder stopped on the Mac (someone ran `ai-mem big`; restore with `ai-mem coder`), or netbird down on the Pi (`netbird status`, `sudo netbird up`) |
| `400 … exceeds the available context size (65536 tokens)` | Conversation too long. Start a new session. Mostly a Claude Code risk. |
| Aider says it can't edit a file | It isn't added: `/add path/to/file` |
| Goose: *OPENAI_API_KEY not set* | Non-login shell: `. ~/.config/local-llm.env` |
| First reply slow, later ones fine | Model was asleep (idle > 5 min) and is reloading; normal |
| Everything slow | Other people are using the coder; check busy slots above |
| Scripted Aider run exits 0 but nothing changed | The model's reply didn't match Aider's edit format, so no edit was applied. Check `git log` for a new commit after each run; try `--edit-format diff` |
| Scripted Goose run exits 0 but printed `Network error` | Goose doesn't fail the exit code on connection errors. Check the output text, not just `$?` |
| Agent did something unwanted | `git diff`; Aider: `/undo`; otherwise `git checkout .` / `git clean -fd` |

## Re-running the tests
The scripts behind [03](03-test-results.md) are in [`scripts/`](scripts/). Copy the folder to the Pi, then:
```bash
./t4-rename.sh aider        # or goose: multi-file rename
./t5-long.sh aider          # 16-turn session (~10–20 min)
./t7-load.sh goose 4        # 4 sessions at once
```
Each writes to `~/harness-tests/` and prints one summary line per run (our own unittest result plus the proxy's
request count, peak prompt, malformed tool calls and HTTP errors).

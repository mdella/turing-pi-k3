# Local Coding-Model Benchmarks — Mac Studio

Which local model can actually drive a coding agent on the Mac Studio (M3 Ultra, 96 GB unified)? Every round below gives Claude Code, pointed at a local model through `claude-local` (Claude Code → Ollama `/v1/messages`), the same autonomous build task and then checks what it produced.

**Current answer:** `qwen3.6:27b` is the only model that has built the task correctly every time (0 defective builds in 8 scored runs). `qwen3-coder-next` (80B-A3B MoE) also passed and is ~2.5× faster; it is the model now served full-time by `llama-server` on :8080. Everything else tested either failed the build or ran out the clock.

> `qwen3.6:27b` was removed from Ollama on 2026-09-23 and `claude-local` still defaults to it — re-pull it or change the default before using `claude-local` without `CLAUDE_LOCAL_MODEL`.

---

## Summary

| Model | Format | Builds | Defective | Mean wall | Gen tok/s | Verdict |
|---|---|---|---|---|---|---|
| `qwen3.6:27b` | GGUF Q4_K_M, 27B dense, 17 GB | 8 | **0** | 14.2 min | ~20 | **Default.** Best quality per GB. |
| `qwen3-coder-next:q4_K_M` | GGUF, 80B-A3B MoE, 51 GB | 1 | 0 † | 8.4 min | ~46–62 | Fastest that passed. Now on llama-server :8080. |
| `qwen3.6:27b-mlx` | MLX | 1 | 1 | timeout | n/a | Correct build, but too slow — hit the 30-min cap at 71 turns. |
| `qwen3.8:27b-mlx` | MLX nvfp4 | 3 (+2 unscored) | 2 | 28.7 min | n/a | Only clean qwen3.8 build came from here. Not reliable. |
| `qwen3.8:27b` | GGUF Q4_K_M | 3 | **3** | timeout | 15.7 | Reasons instead of acting (8 turns/build). |
| `Qwen3.6-35B-A3B-Kimi-K2.6-Distill` | GGUF Q8_0 | 3 (+1) | **3** | 18.6 min | ~51 | Fast and broken. Do not use. |
| `huihui_ai/qwen3-next-abliterated:80b-a3b-instruct` | GGUF | 1 | **1** | 99 min | ~39 | Failed: 70 ruff errors, empty README. |

† Round 1 was scored by independently re-running the model's own tests + ruff + a doc check, not by the black-box acceptance test used from round 2 on.

---

## The task

The same prompt every round — [`taskcli-harness/taskcli-prompt.txt`](taskcli-harness/taskcli-prompt.txt): build `taskcli`, a Python CLI task tracker with a strict three-layer split (`core` / `storage` / `cli`), JSON persistence, `add` / `list [all|open|done]` / `done` / `delete`, type hints, docstrings, error handling, a `pyproject.toml` console script, pytest tests, a clean `ruff check`, and `README.md` + `docs/DESIGN.md`. The agent works unattended with no confirmations.

## How builds are scored

From round 2 on, a build is judged by [`acceptance-test.py`](taskcli-harness/acceptance-test.py), which **drives the real CLI** as a user would — it does not trust the model's own test suite. Each problem is a defect code: `cli-unusable` (won't install or `--help` fails), `add-broken`, `list-broken`, `done-broken`, `delete-broken`, `ids-not-discoverable`, `help-contradiction` (help advertises something that fails), `pytest-fails`, `ruff-fails`, `missing-doc`, and `build-timeout`. **A build is defective if it has any defect code.**

Rules that came out of getting this wrong:

- **A model's own green tests prove nothing.** One build shipped 26 passing tests and clean ruff while `list all` was broken — the test only checked that argparse *accepted* the string.
- **Isolate `HOME` per build.** Builds default to different storage paths under `$HOME` with incompatible schemas; without isolation one build's data makes the next look broken.
- **Only treat `{...}` argparse choices as advertised.** Scraping help prose picks up phrases like "(default: show all)" and invents contradictions.
- **A timeout is a defect.** Builds are capped at 30 min (`TASKCLI_TIMEOUT_S=1800`); an assistant that needs 40 min per task is unusable whether or not it would eventually be right. macOS has no `timeout(1)`, so the runner kills the whole process group.
- **Score from the defect code list, not `defect_count`.** A bug made `cli-unusable` builds report `defect_count: null`, which the aggregator turned into 0 — the worst build in a round was reported as the best. Fixed.

---

## Round 1 — 2026-06-23: first comparison

One build per model. Scored by re-running pytest + ruff and checking the docs.

| Model | Result | Wall | Turns | Output tokens | Notes |
|---|---|---|---|---|---|
| `qwen3-coder-next:q4_K_M` | ✅ pass | 8m24s | 73 | 14.9 K (2.65 M input) | 47 tests, ruff clean, full docs. Fastest. |
| `qwen3.6:27b` | ✅ pass | 14m52s | — | — | Best docs (166-line DESIGN.md), cleanest design. ~20 tok/s, 19 GB resident. |
| `qwen3-next-abliterated:80b-a3b-instruct` | ❌ fail | 98m56s | 79 | 26.4 K | Exit 1, 70 ruff errors, empty README. |

**Takeaway:** coder/instruct tuning and tool-call reliability matter more than size. The abliterated (uncensored) 80B could not hold a multi-step agent loop together. `qwen3.6:27b` became the `claude-local` default.

Run reports: [coder-next](results/2026-06-23-qwen3-coder-next.txt) · [qwen3.6](results/2026-06-23-qwen36-27b.txt) · [abliterated 80B](results/2026-06-23-qwen3-next-abliterated-80b.txt)

## Round 2 — 2026-07-30: qwen3.6 vs Kimi-K2.6 distill

Candidate: `hf.co/lordx64/Qwen3.6-35B-A3B-Kimi-K2.6-Reasoning-Distilled-GGUF:Q8_0`, a 35B-A3B MoE. Its first solo build looked excellent — 6m46s, 26 tests passing, ruff clean ([report](results/2026-07-30-kimi-distill-first-build.txt)) — which is exactly why the black-box acceptance test was written. Three builds each:

| Model | Run | Wall | Turns | Gen tok/s | Defects |
|---|---|---|---|---|---|
| qwen3.6:27b | 1 | 829 s | 28 | 20.9 | — |
| qwen3.6:27b | 2 | 814 s | 23 | 20.6 | — |
| qwen3.6:27b | 3 | 592 s | 32 | 21.4 | — |
| Kimi distill | 1 | 835 s | 39 | 52.1 | `cli-unusable` — `pyproject.toml` names a README it never wrote, so the package won't build |
| Kimi distill | 2 | 767 s | 47 | 49.5 | `add-broken`, `list-broken`, `help-contradiction`, `done-broken`, `delete-broken` |
| Kimi distill | 3 | 1744 s | 0 | 52.1 | `cli-unusable` — produced an empty `src/` |

**qwen3.6: 0/3 defective. Kimi: 3/3.** 2.4× the throughput is worthless at a 100 % defect rate. Raw: [`2026-07-30-qwen36-vs-kimi-distill.json`](results/2026-07-30-qwen36-vs-kimi-distill.json)

## Round 3 — 2026-08-15: invalid (Ollama 0.32.13 bug)

Aborted after one build. The incumbent came back with 8 defects against its own clean baseline. Cause: Ollama 0.32.13's Qwen renderer rejected non-leading system messages (`chat prompt error: "system message must be at the beginning"` → HTTP 500 on `/v1/messages`, ~3.2 % of calls). A multi-turn agent hits that reliably and dies mid-build, which scores as *model* defects. Fixed upstream in 0.32.14 (commit 87abaa019). `run-comparison.sh` now refuses to run on 0.32.13 (`ALLOW_BROKEN_RENDERER=1` overrides). Kept only as a record: [`2026-08-15-INVALID-ollama-0.32.13.json`](results/2026-08-15-INVALID-ollama-0.32.13.json)

## Round 4 — 2026-08-17: is qwen3.8 an upgrade?

Three builds each, 30-min cap, Ollama 0.32.14+.

| Model | Defective | Timeouts | Mean wall | Mean turns | Gen tok/s |
|---|---|---|---|---|---|
| `qwen3.6:27b` | **0/3** | 0 | 991 s | 40.3 | 19.7 |
| `qwen3.8:27b` (GGUF Q4_K_M) | **3/3** | 3 | 1801 s | 8.3 | 15.7 |
| `qwen3.8:27b-mlx` (nvfp4) | **2/3** | 2 | 1721 s | 50.0 | n/a ‡ |

Per run:

| Model | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| qwen3.6:27b | ✅ 1153 s, 59 turns | ✅ 745 s, 33 turns | ✅ 1074 s, 29 turns |
| qwen3.8:27b | ❌ timeout, **2 turns**, no package | ❌ timeout, 10 turns, no package | ❌ timeout, 13 turns, package won't build |
| qwen3.8:27b-mlx | ✅ 1560 s, 52 turns | ❌ timeout, 56 turns, import error | ❌ timeout, 42 turns (tests/ruff/docs otherwise fine) |

**The diagnosis is in the turn counts.** qwen3.8 GGUF isn't working slowly — it barely acts. It spends the clock reasoning inside single responses (one was seen at 14,717 tokens against a 32 K per-response ceiling) instead of making tool calls. The MLX build of the same weights averaged 6× the turns and produced the only clean qwen3.8 build, so part of the failure looks like agent-loop plumbing rather than capability. `qwen3.6:27b` stayed the default. Raw: [`2026-08-17-qwen36-vs-qwen38.json`](results/2026-08-17-qwen36-vs-qwen38.json)

‡ The throughput parser only reads llama.cpp log lines; MLX models report nothing (n/a, not zero).

## Round 5 — 2026-08-22/23: MLX follow-up (incomplete)

The full 3-build round takes ~4 h and was killed three times, so it was split into one-build chunks ([`run-chunk.sh`](taskcli-harness/run-chunk.sh)). Only chunk 1 finished:

| Model | Result |
|---|---|
| `qwen3.6:27b` (GGUF) | ✅ 739 s, 31 turns, 20.4 tok/s |
| `qwen3.6:27b-mlx` | ❌ timeout at 1800 s — but 71 turns and a correct build (tests, ruff, docs all pass). Too slow, not wrong. |
| `qwen3.8:27b-mlx` | not scored — the Claude Code session errored out after 2 turns / 107 s |

**No-thinking experiment.** Since qwen3.8 burns its turns reasoning, [`nothink-proxy.py`](taskcli-harness/nothink-proxy.py) sits between Claude Code and Ollama and rewrites every request to `thinking: {"type": "disabled"}` — the only form this Ollama honours on `/v1/messages`, and one Claude Code never sends. Result with `qwen3.8:27b-mlx`: **timed out at 1800 s with no output at all** ([report](results/2026-08-23-qwen38-mlx-nothink.txt)). Inconclusive — it didn't show whether turning thinking off helps. The round was not resumed.

Raw: [`2026-08-23-qwen36-gguf-vs-mlx-partial.json`](results/2026-08-23-qwen36-gguf-vs-mlx-partial.json)

---

## Related tests (not taskcli rounds)

- **2026-09-23 — agent CLIs on the Raspberry Pi against `qwen3-coder-next` (llama-server :8080):** Goose, Aider and Claude Code through a 7-test plan. → [`rpi-coder-cli/03-test-results.md`](../../rpi-coder-cli/03-test-results.md). Key finding: every harness must be told the real 64 K per-slot context window, or it overflows.
- **2026-09-28 — `huihui-ai/Huihui-Qwen3.8-27B-abliterated` Q8_0 smoke test** (Ollama, not an agent build): ~22 tok/s, correct tool call and follow-up, vision works, no refusals, answers directly with thinking off. Not run through taskcli — plain qwen3.8 already failed round 4, and the abliterated 80B failed round 1. Used as the image prompt-writer in ComfyUI instead.

## Candidates not yet tested

- `Qwen/Qwen-AgentWorld-35B-A3B` (2026-06-22) — small enough to run beside the llama-server coder.
- `Qwen/Qwen3.8-Flash-Next` (2026-08-24, 125B-A6B) — too large: smallest GGUF is 72.5 GB (IQ1_S), Q4 is 111 GB.

---

## Running a round

Harness: [`taskcli-harness/`](taskcli-harness/). Copies of the scripts in `~/projects/taskcli-harness/` on the Mac Studio.

```bash
./run-comparison.sh 3          # 3 builds per model -> comparison-results.json (~4 h)
./run-chunk.sh 1               # one build per model, archived as chunk-1.json
./acceptance-test.py <dir>     # score one build directory
./check-ollama-release.sh      # has a stable Ollama newer than the baseline landed?
```

`run-taskcli-model.sh` does one build: fresh project dir, isolated `HOME`, 30-min watchdog, then collects Claude Code usage and Ollama throughput into `_run-report.txt`. Models are set at the top of `run-comparison.sh`.

Gotchas:

- **Check the Ollama *server* version**, not the client. The daemon is a jax-owned LaunchDaemon; `brew upgrade ollama` swaps the binary but the running server keeps the old build until restarted. `ollama --version` and `/api/version` can disagree — the harness guard reads `/api/version`.
- **Effective agent speed ≪ raw tok/s.** Every turn re-reads the growing context (the coder's round-1 build: 2.65 M input vs 14.9 K output tokens over 73 turns), so context handling matters as much as generation speed.
- `run-chunk.sh` refers to a `merge-chunks.py` that was never written; chunks have to be merged by hand (each reports `run: 1`).

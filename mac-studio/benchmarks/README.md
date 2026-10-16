# Local Coding-Model Benchmarks — Mac Studio

Which local model can actually drive a coding agent on the Mac Studio (M3 Ultra, 96 GB unified)? Every round below gives Claude Code, pointed at a local model through `claude-local` (Claude Code → Ollama `/v1/messages`), the same autonomous build task and then checks what it produced.

**Current answer:** `qwen3.6:27b` is still the most reliable model (1 defective build in 11 scored runs on Ollama, 0 in 3 on oMLX). `qwen3-coder-next` (80B-A3B MoE) also passed and is ~2.5× faster; it is the model now served full-time by `llama-server` on :8080. The strongest new candidate is **`Qwen-AgentWorld-35B-A3B`** (round 6): fast builds (5.7 min mean, ~56 tok/s, 22 GB) and 8 of 9 clean on Ollama — one build crashed on a corrupt data file. Served by **oMLX** instead of Ollama (round 7), the same model built ~30 % faster (3.9 min, ~89 tok/s) but 1 of 3 builds was defective, too few runs to tell the engines apart on quality. Everything else tested either failed the build or ran out the clock.

> `qwen3.6:27b` was removed from Ollama on 2026-09-23 and re-pulled on 2026-10-15 for round 8, so `claude-local`'s default works again.

---

## Summary

| Model | Format | Builds | Defective | Mean wall | Gen tok/s | Verdict |
|---|---|---|---|---|---|---|
| `qwen3.6:27b` (Ollama) | GGUF Q4_K_M, 27B dense, 17 GB | 11 | 1 | 13.0 min | ~20–23 | **Default.** Best quality per GB. 0/8 until round 8, when one build shipped no status filter. |
| `Qwen3.6-27B-4bit` (oMLX) | MLX 4-bit, 16 GB | 3 | **0** | 9.3 min | ~33 | Same model on oMLX (round 8): 1.45× decode, same wall time on 3 builds, ~10 GB less peak memory. |
| `qwen3-coder-next:q4_K_M` | GGUF, 80B-A3B MoE, 51 GB | 1 | 0 † | 8.4 min | ~46–62 | Fast and passed. Now on llama-server :8080. |
| `Qwen-AgentWorld-35B-A3B` (Ollama) | GGUF UD-Q4_K_M, 35B-A3B MoE, 22 GB | 9 | 1 | 5.7 min | ~56 | 8/9 clean; one error-handling defect. Needs the Modelfile fix (see round 6). |
| `Qwen-AgentWorld-35B-A3B` (oMLX) | MLX oQ4 (~4.6 bpw), 20 GB | 3 | 1 | **3.9 min** | ~89 | Fastest yet; same model on a different engine (round 7). One build's `done`/`delete` rejected the ids `list` shows. |
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

From round 2 on, a build is judged by [`acceptance-test.py`](taskcli-harness/acceptance-test.py), which **drives the real CLI** as a user would — it does not trust the model's own test suite. Each problem is a defect code: `cli-unusable` (won't install or `--help` fails), `add-broken`, `list-broken`, `done-broken`, `delete-broken`, `ids-not-discoverable`, `help-contradiction` (help advertises something that fails), `pytest-fails`, `ruff-fails`, `missing-doc`, `no-status-filter` (no form of `list` shows only open or only done tasks), and `build-timeout`. **A build is defective if it has any defect code.**

Rules that came out of getting this wrong:

- **A model's own green tests prove nothing.** One build shipped 26 passing tests and clean ruff while `list all` was broken — the test only checked that argparse *accepted* the string.
- **Isolate `HOME` per build.** Builds default to different storage paths under `$HOME` with incompatible schemas; without isolation one build's data makes the next look broken.
- **Only treat `{...}` argparse choices as advertised.** Scraping help prose picks up phrases like "(default: show all)" and invents contradictions.
- **A timeout is a defect.** Builds are capped at 30 min (`TASKCLI_TIMEOUT_S=1800`); an assistant that needs 40 min per task is unusable whether or not it would eventually be right. macOS has no `timeout(1)`, so the runner kills the whole process group.
- **Probe for what the prompt asks, not for a command name.** The prompt says "mark a task done by id"; a build that ships `mark <id>` instead of `done <id>` is fine. And check that a required feature *exists*, not only that advertised features work: until round 8 a build with no status filter at all passed, because only filters named in `--help` were tested. Both fixed 2026-10-15 (`no-status-filter` defect code); all 27 kept builds were re-scored and only that build's score changed.
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

## Round 6 — 2026-09-29: Qwen-AgentWorld-35B-A3B

Candidate: [`Qwen/Qwen-AgentWorld-35B-A3B`](https://huggingface.co/Qwen/Qwen-AgentWorld-35B-A3B) (2026-06-22, Qwen3.5-35B-A3B base), GGUF `unsloth/Qwen-AgentWorld-35B-A3B-GGUF:UD-Q4_K_M` (22 GB — fits beside the resident llama-server coder, so no `ai-mem big`). It is a *language world model*: trained to simulate agent environments (predict the next tool/terminal state) with long chain-of-thought, and claimed to transfer to acting as the agent. Long per-turn reasoning is how qwen3.8 failed, so turn counts were the thing to watch. Ollama 0.34.3, three builds, 30-min cap.

**The raw `hf.co` pull cannot be benchmarked.** Ollama renders it with the GGUF's embedded Jinja chat template, which calls `raise_exception('System message must be at the beginning.')` on any non-leading system message — the round-3 Ollama 0.32.13 failure, now shipped inside the model file. Claude Code sends those mid-conversation, so the first build died at turn 1 with HTTP 500 after 180 s ([report](results/2026-09-29-INVALID-agentworld-jinja-500.txt)); the round was stopped rather than record three harness failures as model defects. Fix: re-create the same weights with Ollama's built-in Qwen3.5 renderer, exactly as the official `qwen3.5:35b-a3b` library model is configured, plus the model card's sampling — [`agentworld.Modelfile`](taskcli-harness/agentworld.Modelfile):

```
FROM hf.co/unsloth/Qwen-AgentWorld-35B-A3B-GGUF:UD-Q4_K_M
RENDERER qwen3.5
PARSER qwen3.5
PARAMETER temperature 0.6
PARAMETER top_p 0.95
PARAMETER top_k 20
```

`ollama create agentworld:35b-a3b-q4km -f agentworld.Modelfile`. A mid-conversation system message then returns a correct tool call instead of a 500.

| Run | Wall | Turns | Gen tok/s | Output tokens | Result |
|---|---|---|---|---|---|
| 1 | 287 s | 36 | 61.3 | 15.7 K | ✅ 35 tests, ruff clean, README 122 / DESIGN 139 lines |
| 2 | 357 s | 52 | 58.2 | 17.8 K | ❌ `crash-on-corrupt-db` — traceback on a malformed JSON file (the prompt requires handling it). Everything else works. |
| 3 | 485 s | 46 | 49.2 | 19.8 K | ✅ 36 tests, ruff clean, README 215 / DESIGN 118 lines |
| 4 | 323 s | 29 | 61.3 | 18.6 K | ✅ 21 tests, ruff clean, README 97 / DESIGN 98 lines |
| 5 | 301 s | 40 | 55.9 | 14.5 K | ✅ 30 tests, ruff clean, README 106 / DESIGN 156 lines |
| 6 | 317 s | 34 | 48.1 | 12.7 K | ✅ 28 tests, ruff clean, README 146 / DESIGN 134 lines |

Runs 4–6 are a second batch run the same day (tag `aw2`) to firm up the defect rate after the first batch came back 1/3.

**1/6 defective, mean 345 s, 39.5 turns, ~56 tok/s.** The world-model training did not stall the loop: it averaged 40 turns per build (qwen3.6 ~34, qwen3.8 GGUF 8.3) and finished every build in under 8½ minutes — 2.5× faster than the `qwen3.6:27b` mean for ~30 % more memory (22 vs 17 GB). The one defect is a real error-handling miss, not a broken command, and the second batch was 3/3 clean, so 1/6 looks like an occasional miss rather than a pattern. It still keeps AgentWorld just behind `qwen3.6:27b`'s 0/8 record. Not compared same-day: `qwen3.6:27b` is no longer installed, so its recorded baseline stands in. Raw: [batch 1](results/2026-09-29-agentworld-35b-a3b.json) · [batch 2](results/2026-09-29-agentworld-35b-a3b-batch2.json)

**Harness fix in this round:** the end-of-round summary in `run-comparison.sh` still counted defective builds from `defect_count`, the bug described above; it now counts from the defect code list.

## Round 7 — 2026-10-15: same model, oMLX vs Ollama

Question: does serving the model with [oMLX](https://github.com/jundot/omlx) (an MLX inference server for Apple Silicon with continuous batching and a RAM + SSD prefix cache) instead of Ollama make agent builds faster or better? Model: [`mlx-community/Qwen-AgentWorld-35B-A3B-oQ4`](https://huggingface.co/mlx-community/Qwen-AgentWorld-35B-A3B-oQ4), oMLX's own mixed-precision quant (~4.6 bpw, 19.9 GB), against round 6's Ollama build (GGUF UD-Q4_K_M). Same sampling on both (temp 0.6, top_p 0.95, top_k 20 — [`omlx/model_settings.json`](omlx/model_settings.json)). oMLX 0.7.0 in a uv venv on 127.0.0.1:8000; Ollama 0.34.3. **llama-server was stopped** (`ai-mem big`) for the whole round, and before each build the other engine's copy was unloaded, so each build had the machine to itself. Ollama was re-run as a control (`awc`) because round 6's builds had the coder resident.

oMLX needs no Modelfile-style fix: it rewrites mid-conversation system messages as user notes instead of failing, and Anthropic `/v1/messages` tool calls work. Claude Code talks to it directly (`ANTHROPIC_BASE_URL=http://127.0.0.1:8000`); `claude-local` only knows Ollama's API.

**Direct measurements first** (no agent; [`omlx/prefill-bench.py`](omlx/prefill-bench.py), [`omlx/interleave-bench.py`](omlx/interleave-bench.py)):

| | oMLX | Ollama |
|---|---|---|
| Decode, 7 K-token prompt | **103 tok/s** | 75 tok/s |
| Decode, 26 K-token prompt | **91 tok/s** | 67 tok/s |
| Prefill, cold | 2,000–2,200 tok/s | 1,640–2,000 tok/s |
| 26 K prompt, cold → first token | 12.8 s | 15.7 s |
| Same conversation, next turn | 1.1 s | 1.7 s |
| …after two other 26 K conversations in between | 1.2 s | 1.7 s |
| Two 7 K requests at once, wall | 7.1 s | 8.5 s |
| Memory (process / model) | 20 GB, peak 25 | 23.5 GB at 2 × 64 K ctx |

The prefix cache is **not** oMLX's advantage for this model: Ollama also kept each conversation's prefix and served the next turn in under 2 s, even with other conversations in between. The gain is decode speed. Raw: [`2026-10-15-agentworld-omlx-vs-ollama-direct.jsonl`](results/2026-10-15-agentworld-omlx-vs-ollama-direct.jsonl)

**taskcli builds**, interleaved oMLX / Ollama, 30-min cap:

| Engine | Run | Wall | Turns | Gen tok/s | Output tokens | Result |
|---|---|---|---|---|---|---|
| oMLX | 1 | 255 s | 41 | 88.6 | 14.8 K | ❌ `done-broken`, `delete-broken` — `list` prints an 8-char id prefix, but `done`/`delete` only accept the full UUID. Its own 27 tests pass. |
| oMLX | 2 | 206 s | 29 | 89.8 | 13.8 K | ✅ 34 tests, ruff clean, README 198 / DESIGN 150 lines |
| oMLX | 3 | 243 s | 38 | 88.7 | 15.8 K | ✅ 39 tests, ruff clean, README 125 / DESIGN 122 lines |
| Ollama | 1 | 293 s | 39 | 61.3 | 15.3 K | ✅ 32 tests, ruff clean, README 159 / DESIGN 149 lines |
| Ollama | 2 | 406 s | 34 | 52.9 | 16.7 K | ✅ 31 tests, ruff clean, README 130 / DESIGN 194 lines |
| Ollama | 3 | 309 s | 32 | 56.4 | 14.4 K | ✅ 29 tests, ruff clean, README 123 / DESIGN 139 lines |

| Engine | Defective | Mean wall | Mean turns | Gen tok/s | Peak system memory |
|---|---|---|---|---|---|
| oMLX | 1/3 | **235 s** | 36.0 | **89.0** | 42.9–44.8 GB |
| Ollama | 0/3 | 336 s | 35.0 | 56.9 | 44.6–45.3 GB |

**oMLX builds ~30 % faster at the same turn count and memory; quality is not distinguishable on 3 runs.** Per build, oMLX served 94–96 % of prompt tokens from its cache and prefilled the rest at ~1,000–1,200 tok/s; Ollama's builds prefilled at ~560–620 tok/s. Peak memory is system-wide (baseline ~20 GB of other services), so each engine added ~23–25 GB; swap stayed flat at 24.1 GB. The oMLX defect is a real usability bug, of the same "works in its own tests, fails as a user" kind the acceptance test was written for; with it AgentWorld stands at 1/9 on Ollama and 1/3 on oMLX. Raw: [`2026-10-15-agentworld-omlx-vs-ollama.json`](results/2026-10-15-agentworld-omlx-vs-ollama.json)

Not answered here: the dense `qwen3.8:27b` (Hermes' model) already runs on Ollama's MLX engine, so these MoE numbers don't predict whether oMLX helps it.

**Harness changes in this round:** a model named `omlx/<id>` is run against oMLX instead of Ollama; `run-comparison.sh` unloads the other engine before each build; every build samples system memory and swap every 10 s; and the summary adds mean turns and peak memory. oMLX throughput comes from the difference between `/api/status` snapshots taken before and after the build.

## Round 8 — 2026-10-15: qwen3.6 27B, oMLX vs Ollama

Round 7's setup applied to the incumbent. oMLX: [`mlx-community/Qwen3.6-27B-4bit`](https://huggingface.co/mlx-community/Qwen3.6-27B-4bit) (plain 4-bit affine, group size 64, 16 GB; oMLX loads it with its VLM engine because the checkpoint carries vision weights), sampling copied from Ollama's library model (temp 1.0, top_p 0.95, top_k 20, min_p 0). Ollama: `qwen3.6:27b` re-pulled (it had been removed 2026-09-23) as a same-day control. llama-server stopped, the other engine unloaded before each build. Both pass the mid-conversation system message and tool-call checks.

**Direct measurements** ([`omlx/prefill-bench.py`](omlx/prefill-bench.py) with `BENCH_OLLAMA_MODEL=qwen3.6:27b BENCH_OMLX_MODEL=qwen3.6-27b-4bit`):

| | oMLX | Ollama |
|---|---|---|
| Decode, 7 K-token prompt | **37 tok/s** | 20–21 tok/s |
| Decode, 26 K-token prompt | **34 tok/s** | 17–19 tok/s |
| Prefill, cold | ~320–350 tok/s | ~280–300 tok/s |
| 26 K prompt, cold → first token | 80 s | 92 s |
| Same conversation, next turn | **4.7 s** | 8.6 s |

The dense 27B gains more from oMLX than the MoE did (1.8× decode vs 1.35×). Raw: [`2026-10-15-qwen36-omlx-vs-ollama-direct.jsonl`](results/2026-10-15-qwen36-omlx-vs-ollama-direct.jsonl)

**taskcli builds**, interleaved, 30-min cap:

| Engine | Run | Wall | Turns | Gen tok/s | Output tokens | Result |
|---|---|---|---|---|---|---|
| oMLX | 1 | 622 s | 35 | 33.1 | 15.5 K | ✅ 43 tests, ruff clean, README 74 / DESIGN 84 lines |
| oMLX | 2 | 507 s | 25 | 33.7 | 12.0 K | ✅ 22 tests, ruff clean, README 77 / DESIGN 87 lines |
| oMLX | 3 | 551 s | 40 | 33.1 | 13.8 K | ✅ 38 tests, ruff clean, README 87 / DESIGN 81 lines |
| Ollama | 1 | 441 s | 25 | 23.5 | 7.8 K | ❌ `no-status-filter` — `list` takes no arguments at all; the prompt requires all / open / done filtering. (First scored `done-broken`: the command is `mark <id>`, which works — see the scoring rules.) |
| Ollama | 2 | 737 s | 37 | 22.4 | 12.8 K | ✅ 35 tests, ruff clean, README 85 / DESIGN 70 lines |
| Ollama | 3 | 560 s | 25 | 23.1 | 10.2 K | ✅ 26 tests, ruff clean, README 78 / DESIGN 101 lines |

| Engine | Defective | Mean wall | Mean turns | Gen tok/s | Peak system memory |
|---|---|---|---|---|---|
| oMLX | **0/3** | 560 s | 33.3 | **33.3** | 40.7–42.9 GB |
| Ollama | 1/3 | 579 s | 29.0 | 23.0 | 46.2–53.2 GB |

**Same wall clock despite 1.45× faster decode.** The oMLX builds did more: more turns (33 vs 29) and more output (12–15.5 K vs 7.8–12.8 K tokens), and decode time dominates a dense model's build (357–468 s of each oMLX build). Per build, oMLX served 93–98 % of prompt tokens from cache and prefilled the rest at 220–270 tok/s; Ollama's prefill ran at 150–190 tok/s. Ollama's `qwen3.6:27b` now ships `draft_num_predict 3` (speculative drafting), which likely explains its ~23 tok/s in builds versus ~20 in earlier rounds and in the direct test. Memory: oMLX peaked ~10 GB lower (the baseline is ~18 GB of other services; Ollama reserves 2 × 64 K context and loads the vision projector).

So for qwen3.6 oMLX doesn't make builds finish sooner, but it ran them clean on less memory, and its faster decode shows up directly in interactive use (first-token and per-token latency). The Ollama defect is the model's, not the engine's — qwen3.6 now stands at 1/11 on Ollama. Raw: [`2026-10-15-qwen36-omlx-vs-ollama.json`](results/2026-10-15-qwen36-omlx-vs-ollama.json) (Ollama run 1 carries its original score under `rescored`).

Earlier, Ollama's *own* MLX engine ran this model correctly but timed out at 71 turns (round 5). oMLX's MLX build needed 25–40 turns and finished in ~9 min, so that slowness was the engine, not MLX.

---

## Related tests (not taskcli rounds)

- **2026-09-23 — agent CLIs on the Raspberry Pi against `qwen3-coder-next` (llama-server :8080):** Goose, Aider and Claude Code through a 7-test plan. → [`rpi-coder-cli/03-test-results.md`](../../rpi-coder-cli/03-test-results.md). Key finding: every harness must be told the real 64 K per-slot context window, or it overflows.
- **2026-09-28 — `huihui-ai/Huihui-Qwen3.8-27B-abliterated` Q8_0 smoke test** (Ollama, not an agent build): ~22 tok/s, correct tool call and follow-up, vision works, no refusals, answers directly with thinking off. Not run through taskcli — plain qwen3.8 already failed round 4, and the abliterated 80B failed round 1. Used as the image prompt-writer in ComfyUI instead.

## Candidates not yet tested

- `Qwen/Qwen3.8-Flash-Next` (2026-08-24, 125B-A6B) — too large: smallest GGUF is 72.5 GB (IQ1_S), Q4 is 111 GB.

---

## Running a round

Harness: [`taskcli-harness/`](taskcli-harness/). Copies of the scripts in `~/projects/taskcli-harness/` on the Mac Studio.

```bash
./run-comparison.sh 3          # 3 builds per model -> comparison-results.json (~35 min round 7, ~1 h round 8, ~4 h older 27B rounds)
./run-chunk.sh 1               # one build per model, archived as chunk-1.json
./acceptance-test.py <dir>     # score one build directory
./check-ollama-release.sh      # has a stable Ollama newer than the baseline landed?
```

`run-taskcli-model.sh` does one build: fresh project dir, isolated `HOME`, 30-min watchdog, then collects Claude Code usage, server throughput and memory/swap samples into `_run-report.txt`. Models are set at the top of `run-comparison.sh`; prefix one with `omlx/` (e.g. `om:omlx/agentworld-oq4`) to run it on oMLX instead of Ollama.

oMLX (round 7): [`omlx/`](omlx/) holds `start-omlx.sh` (start/stop the trial server on 127.0.0.1:8000), the per-model settings, and the two direct benchmarks. The scripts expect to live in `~/projects/omlx-trial/` beside its `.venv` (`uv venv --python 3.12` + the oMLX 0.7.0 cp312 wheel from its GitHub release) and `models/`. The server renames its process to `omlx-server`, so find it by port, not by name. Its unload endpoint wants the model's directory name, not the alias.

Gotchas:

- **Check the Ollama *server* version**, not the client. The daemon is a jax-owned LaunchDaemon; `brew upgrade ollama` swaps the binary but the running server keeps the old build until restarted. `ollama --version` and `/api/version` can disagree — the harness guard reads `/api/version`.
- **Effective agent speed ≪ raw tok/s.** Every turn re-reads the growing context (the coder's round-1 build: 2.65 M input vs 14.9 K output tokens over 73 turns), so context handling matters as much as generation speed.
- `run-chunk.sh` refers to a `merge-chunks.py` that was never written; chunks have to be merged by hand (each reports `run: 1`).

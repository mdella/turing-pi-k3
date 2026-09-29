#!/usr/bin/env bash
#
# run-comparison.sh — build taskcli N times with each model and compare defect
# rates using the black-box acceptance test (NOT the models' own test suites,
# which have already been shown to pass while the CLI is broken).
#
#   ./run-comparison.sh [runs]     # default 3
#
# Results: /Users/mdella/projects/taskcli-harness/comparison-results.json
#
# MODELS UNDER TEST (2026-08-22) — engine-controlled rerun
#   qwen3.6:27b       incumbent, GGUF / Q4_K_M, llama.cpp engine.
#   qwen3.6:27b-mlx   SAME MODEL as MLX / nvfp4. This is the control: it
#                     isolates the ENGINE from the MODEL. The previous round
#                     showed 3.8-MLX driving the agent loop far better than
#                     3.8-GGUF (50 turns vs 8.3), but with only one model tested
#                     both ways there was no way to tell whether MLX helps
#                     generally or 3.8 is simply broken in GGUF.
#   qwen3.8:27b-mlx   successor, MLX / nvfp4.
#
# qwen3.8:27b (GGUF) IS NO LONGER TESTABLE UNDER THAT NAME. It went 3/3 defective
# on 2026-08-17 (all timeouts) and was deleted; upstream has since REPOINTED the
# `27b` tag at the MLX build. Verified 2026-08-22: qwen3.8:27b and
# qwen3.8:27b-mlx are byte-identical manifests (sha256 5642e97495e1..., 1209
# tensor layers, 18.2 GB). Pulling `qwen3.8:27b` today gets you MLX, not GGUF, so
# running both would be duplicate work.
#
# PRIOR ROUND (2026-08-17), for reference:
#   qwen3.6:27b      0/3 defective, mean 991 s, 40.3 turns, 19.7 tok/s
#   qwen3.8:27b GGUF 3/3 defective, all timeouts, 8.3 turns
#   qwen3.8:27b-mlx  2/3 defective, 50.0 turns, one clean build at 1560 s
#
# ORIGINAL 2026-08-16 NOTES BELOW
#   qwen3.6:27b       the incumbent / claude-local default. Baseline from the
#                     2026-07-30 round: 0/3 defective, ~21 tok/s, mean 745 s.
#   qwen3.8:27b       successor, GGUF / Q4_K_M, 17.7 GB, llama.cpp engine.
#   qwen3.8:27b-mlx   the SAME model as an Apple-Silicon build: safetensors /
#                     nvfp4, 18.2 GB, Ollama's MLX engine. Announced in v0.32.12
#                     literally as `ollama run qwen3.8:27b-mlx`.
#
# Both 3.8 builds declare vision + thinking, which 3.6 does not. THINKING IS THE
# THING TO WATCH: a model that reasons before every tool call can burn the turn
# budget on deliberation and stall the agent loop, which is how the abliterated
# 80B failed (99 min, ruff dirty, empty README).
#
# GGUF vs MLX is the comparison no previous round could make: same weights, same
# task, two engines. Expect the difference in tok/s, not in defects -- if the
# two 3.8 builds disagree on DEFECTS, suspect the harness or the renderer before
# believing the engine changed the model's judgement.
#
# !! DO NOT RUN ON OLLAMA 0.32.13 !!
# 0.32.13 added a qwen prompt renderer that rejects non-leading system messages:
#   ERROR "chat prompt error" error="system message must be at the beginning"
#   POST /v1/messages?beta=true -> 500
# Measured 2026-08-15: 23 x 500 against 688 x 200, a ~3.2% per-request failure
# rate. That is fatal to a 14+ turn agent build -- it killed the incumbent's
# run 1 (terminal_reason=api_error at 14 turns, empty tests/ and docs/) and
# scored the half-built project 8 defects against its own 0/3 baseline. The
# numbers were measuring the endpoint, not the models.
# Fixed upstream by commit 87abaa019 "renderers/qwen: tolerate non-leading
# system messages", first tagged in v0.32.14-rc0. Wait for 0.32.14 stable, or
# run a HEAD build. Downgrading is NOT a fix: 0.32.13 is also the release that
# added qwen3.8 support in the first place.
#
# Tags are q36/q38/q38mlx, not "qwen", so this round does not delete the
# 2026-07-30 build artifacts under ~/projects/taskcli-cmp-qwen-*.
#
# The devstral / qwen3-coder:30b round drafted here on 2026-08-03 never ran;
# neither model is installed. Dropped rather than silently left in the list.
#
# The Kimi-K2.6 distill was dropped earlier and deleted from Ollama: 3/3
# defective (broken pyproject readme, an `add --title` that rejected its own
# documented flag, and one run that produced an empty src/ after 29 minutes).
# 2.4x throughput is worthless at a 100% defect rate.
#
set -uo pipefail

RUNS="${1:-3}"
HERE="$(cd "$(dirname "$0")" && pwd)"
RESULTS="$HERE/comparison-results.json"

# tag:model — tag becomes the project suffix, so keep it short and filename-safe
#
# 2026-09-29: Qwen-AgentWorld-35B-A3B alone (Qwen3.5-35B-A3B base, UD-Q4_K_M,
# 22 GB -- fits beside llama-server's resident coder, so no `ai-mem big`).
# It is a "language world model": trained to SIMULATE agent environments with
# long chain-of-thought, claimed to transfer to acting as the agent. Long
# reasoning per turn is the qwen3.8 failure shape -- watch the turn counts.
# The incumbent qwen3.6:27b is no longer installed; compare against its
# recorded 0/8 baseline rather than a same-day rerun.
# Previous round's list: q36:qwen3.6:27b q36mlx:qwen3.6:27b-mlx q38mlx:qwen3.8:27b-mlx
#
# The raw hf.co pull is NOT testable: Ollama renders it with the GGUF's embedded
# Jinja template, which raise_exception()s on any non-leading system message --
# the same failure as Ollama 0.32.13, now shipped inside the model file. The
# first run died at turn 1 with HTTP 500 after 180 s. agentworld:35b-a3b-q4km is
# the same weights re-created with the official library qwen3.5 settings
# (RENDERER/PARSER qwen3.5, no template) + the model card's sampling
# (temp 0.6, top_p 0.95, top_k 20). Modelfile: agentworld.Modelfile.
MODELS=(
  "aw2:agentworld:35b-a3b-q4km"   # second batch of 3 (first batch: tag aw)
)

# --- preflight -------------------------------------------------------------
# Two things sink a run hours in if not checked up front: the model isn't
# pulled, or it lacks the `tools` capability and therefore cannot drive the
# agent loop at all (vision-only models fail this way, silently producing zero
# turns).
echo "=== preflight ==="

# Version guard. On 0.32.13 the qwen renderer 500s on ~3% of requests and a run
# dies at a random turn count, so the comparison measures luck. Refuse rather
# than produce numbers that look real. Override only if you are deliberately
# characterising the failure: ALLOW_BROKEN_RENDERER=1 ./run-comparison.sh
srv_ver="$(curl -fsS http://localhost:11434/api/version 2>/dev/null |
           sed -n 's/.*"version":"\([^"]*\)".*/\1/p')"
echo "  ollama server            ${srv_ver:-UNREACHABLE}"
if [ -z "$srv_ver" ]; then
  echo "  cannot reach Ollama at localhost:11434 — is the daemon up?"
  exit 1
fi
if [ "$srv_ver" = "0.32.13" ] && [ "${ALLOW_BROKEN_RENDERER:-0}" != "1" ]; then
  cat >&2 <<'MSG'

  REFUSING TO RUN on Ollama 0.32.13.

  This build rejects non-leading system messages in the qwen renderer:
    "chat prompt error" error="system message must be at the beginning"  -> 500
  Measured ~3.2% of /v1/messages calls (23 of 711). A multi-turn agent build
  hits that reliably and dies mid-run, which scores as model defects.

  Fixed by 87abaa019 "renderers/qwen: tolerate non-leading system messages",
  first tagged v0.32.14-rc0. Upgrade to 0.32.14 stable when it lands.
  Do NOT downgrade — 0.32.13 is what added qwen3.8 support.

  To characterise the failure anyway: ALLOW_BROKEN_RENDERER=1 ./run-comparison.sh
MSG
  exit 1
fi

missing=0
installed="$(ollama list 2>/dev/null | awk 'NR>1 {print $1}')"
for spec in "${MODELS[@]}"; do
  tag="${spec%%:*}"
  model="${spec#*:}"

  if ! printf '%s\n' "$installed" | grep -Fxq -- "$model"; then
    printf "  %-10s %-22s NOT PULLED — run: ollama pull %s\n" "$tag" "$model" "$model"
    missing=1
    continue
  fi

  # Capture first, then match. Do NOT pipe `ollama show` into `grep -q`: grep
  # exits at the first match, `ollama show` then dies of SIGPIPE, and with
  # `set -o pipefail` the pipeline reports failure even though the match
  # SUCCEEDED. That misreported every installed model as lacking `tools`.
  # Also note [[:space:]] rather than \s -- BSD grep does not understand \s.
  show_out="$(ollama show "$model" 2>/dev/null)"
  if printf '%s\n' "$show_out" | grep -qE '^[[:space:]]*tools[[:space:]]*$'; then
    caps=ok
  else
    caps="NO TOOLS CAPABILITY — cannot drive the agent loop"
    missing=1
  fi
  printf "  %-10s %-22s %s\n" "$tag" "$model" "$caps"
done
if [ "$missing" != "0" ]; then
  echo
  echo "preflight failed — fix the above and re-run."
  exit 1
fi
echo

echo "[" > "$RESULTS"
first=1

for i in $(seq 1 "$RUNS"); do
  for spec in "${MODELS[@]}"; do
    tag="${spec%%:*}"
    model="${spec#*:}"
    suffix="cmp-$tag-$i"
    proj="/Users/mdella/projects/taskcli-$suffix"

    echo ""
    echo "############ run $i/$RUNS — $tag ($model) ############"
    rm -rf "$proj"

    "$HERE/run-taskcli-model.sh" "$model" "$suffix" >/dev/null 2>&1
    rc=$?

    wall=$(grep -o 'wall_clock_s: [0-9]*' "$proj/_run-report.txt" 2>/dev/null | awk '{print $2}')
    gen=$(grep -o 'mean=[0-9.]* tok/s' "$proj/_run-report.txt" 2>/dev/null | head -1 | tr -d 'mean=' | awk '{print $1}')
    turns=$(grep -o 'num_turns      : [0-9]*' "$proj/_run-report.txt" 2>/dev/null | awk '{print $3}')

    acc=$(python3 "$HERE/acceptance-test.py" "$proj" 2>/dev/null)
    [ -z "$acc" ] && acc='{"defect_count":null,"defects":[{"code":"acceptance-test-failed","detail":"no output"}],"notes":{}}'

    [ $first -eq 0 ] && echo "," >> "$RESULTS"
    first=0
    python3 - "$tag" "$i" "$rc" "${wall:-0}" "${gen:-0}" "${turns:-0}" "$acc" "$model" >> "$RESULTS" <<'PY'
import json, sys
tag, i, rc, wall, gen, turns, acc, model = sys.argv[1:9]
a = json.loads(acc)
print(json.dumps({
    "model": tag, "ollama_model": model, "run": int(i), "exit_code": int(rc),
    "wall_s": int(float(wall)), "gen_tok_s": float(gen), "turns": int(turns),
    "defect_count": a.get("defect_count"),
    "defects": [d["code"] for d in a.get("defects", [])],
    "defect_detail": a.get("defects", []),
    "notes": a.get("notes", {}),
}, indent=2))
PY
    echo "  -> exit=$rc wall=${wall}s defects=$(echo "$acc" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("defect_count"))')"
  done
done

echo "]" >> "$RESULTS"

echo
echo "results: $RESULTS"
echo
echo "=== defect rate by model ==="
python3 - "$RESULTS" <<'PY'
import json, sys
from collections import defaultdict
rows = json.load(open(sys.argv[1]))
agg = defaultdict(list)
for r in rows:
    agg[r["model"]].append(r)
print(f"  {'model':10} {'defective':>10} {'mean wall':>10} {'mean tok/s':>11}")
for m, rs in agg.items():
    # Count from the defect CODE list: a cli-unusable build reports
    # defect_count null, which `or 0` used to score as clean.
    bad = sum(1 for r in rs if r.get("defects"))
    mw = sum(r["wall_s"] for r in rs) / len(rs)
    mt = sum(r["gen_tok_s"] for r in rs) / len(rs)
    print(f"  {m:10} {bad:>6}/{len(rs):<3} {mw:>9.0f}s {mt:>10.1f}")
PY

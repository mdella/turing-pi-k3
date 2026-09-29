#!/usr/bin/env bash
#
# run-taskcli-model.sh — drive `claude-local` against one Ollama model on the
# same agentic build task, and collect comparable timing/throughput stats.
#
#   ./run-taskcli-model.sh <ollama-model> <project-suffix>
#
# e.g. ./run-taskcli-model.sh 'qwen3.6:27b' qwen36
#      -> builds in ~/projects/taskcli-qwen36, writes _run-report.txt there
#
# Stats collected:
#   * wall clock + exit code
#   * Claude Code usage from `claude -p --output-format json`
#     (input/output tokens, num_turns, api duration)
#   * Ollama server-side throughput, by slicing the ollama log to just the
#     window of this run, so numbers are not polluted by other activity.
#
set -uo pipefail

MODEL="${1:?usage: run-taskcli-model.sh <model> <suffix>}"
SUFFIX="${2:?usage: run-taskcli-model.sh <model> <suffix>}"

PROJ="/Users/mdella/projects/taskcli-$SUFFIX"
# Absolute: this script cd's into $PROJ before reading the prompt, so a relative
# dirname would resolve against the wrong directory.
HERE="$(cd "$(dirname "$0")" && pwd)"
PROMPT="$HERE/taskcli-prompt.txt"
OLLAMA_LOG=/Users/Shared/ollama/ollama.log
REPORT="$PROJ/_run-report.txt"

[ -f "$PROMPT" ] || { echo "missing prompt: $PROMPT"; exit 1; }
command -v claude-local >/dev/null || { echo "claude-local not on PATH"; exit 1; }

mkdir -p "$PROJ"
cd "$PROJ" || exit 1

# Mark our starting point in the ollama log so we only measure THIS run.
LOG_START=$(wc -l < "$OLLAMA_LOG" 2>/dev/null || echo 0)
START_S=$(date +%s)

echo "=== taskcli build via claude-local ===" | tee "$REPORT"
{
  echo "model:        $MODEL"
  echo "project:      $PROJ"
  echo "start:        $(date)"
} | tee -a "$REPORT"

# PER-BUILD TIMEOUT
# Runs used to be unbounded, which is fine until a reasoning model decides to
# think instead of act: qwen3.8:27b spent 22 minutes inside ONE response that
# had reached 14,717 tokens and was still generating, against a 32,000-token
# per-response ceiling. Three models x 3 runs of that is an overnight job.
#
# A cap is also the more honest measurement. An assistant that takes 40 minutes
# to produce a single reply is unusable for interactive coding whether or not it
# would eventually have emitted something correct, so a timeout is a real defect
# and is scored as one (see _TIMEOUT below), not silently discarded.
#
# macOS ships no timeout(1) and gtimeout is not installed, so this is a manual
# watchdog. `set -m` puts the build in its own process group, which matters:
# claude spawns children, and killing only the top pid leaves them running and
# holding the model resident for the next run.
TIMEOUT_S="${TASKCLI_TIMEOUT_S:-1800}"
echo "timeout:      ${TIMEOUT_S}s" | tee -a "$REPORT"

# --dangerously-skip-permissions: unattended agentic run in a throwaway dir.
set -m
CLAUDE_LOCAL_MODEL="$MODEL" claude-local \
  -p "$(cat "$PROMPT")" \
  --output-format json \
  --dangerously-skip-permissions \
  > "$PROJ/_build-result.json" 2> "$PROJ/_build-stderr.log" &
BUILD_PID=$!
set +m

(
  sleep "$TIMEOUT_S"
  kill -0 "$BUILD_PID" 2>/dev/null || exit 0
  kill -TERM -"$BUILD_PID" 2>/dev/null || kill -TERM "$BUILD_PID" 2>/dev/null
  sleep 15
  kill -KILL -"$BUILD_PID" 2>/dev/null || kill -KILL "$BUILD_PID" 2>/dev/null
) & WATCHDOG=$!

wait "$BUILD_PID"; EXIT=$?
kill "$WATCHDOG" 2>/dev/null; wait "$WATCHDOG" 2>/dev/null

END_S=$(date +%s)
WALL=$((END_S - START_S))

# Attribute by elapsed time, not by exit status alone: a build killed by the
# watchdog exits 143/137, but so does one the user interrupts, and those must
# not be recorded as the model timing out.
if [ "$WALL" -ge "$((TIMEOUT_S - 5))" ]; then
  echo "TIMEOUT after ${TIMEOUT_S}s (killed mid-build)" > "$PROJ/_TIMEOUT"
  echo "  !! TIMED OUT after ${TIMEOUT_S}s — scored as a defect" | tee -a "$REPORT"
fi

{
  echo "end:          $(date)"
  echo "exit_code:    $EXIT"
  printf "wall_clock_s: %d  (%dm%02ds)\n" "$WALL" $((WALL/60)) $((WALL%60))
  echo
  echo "--- Claude Code usage ---"
} | tee -a "$REPORT"

python3 - "$PROJ/_build-result.json" <<'PY' | tee -a "$REPORT"
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    if isinstance(d, list):
        d = next((x for x in reversed(d) if isinstance(x, dict) and 'usage' in x), d[-1])
    u = d.get('usage', {}) or {}
    it = u.get('input_tokens', 0) + u.get('cache_read_input_tokens', 0)
    ot = u.get('output_tokens', 0)
    api = d.get('duration_api_ms', 0)
    print(f"  input_tokens   : {it}")
    print(f"  output_tokens  : {ot}")
    print(f"  num_turns      : {d.get('num_turns','?')}")
    print(f"  duration_api_ms: {api}")
    if api:
        print(f"  effective_out_tok/s: {ot/(api/1000):.1f}")
    if d.get('is_error') or d.get('subtype') not in (None, 'success'):
        print(f"  RESULT         : {d.get('subtype')}  is_error={d.get('is_error')}")
except Exception as e:
    print(f"  parse error: {e}")
PY

{
  echo
  echo "--- Ollama server-side throughput (this run only) ---"
} | tee -a "$REPORT"

tail -n "+$((LOG_START+1))" "$OLLAMA_LOG" 2>/dev/null | python3 -c "
import sys, re
# Ignore generations shorter than MIN_TOK. A 1-token generation finishing in
# 0.4 ms reports ~2600 tok/s, which swamps the mean and is not a real rate.
MIN_TOK = 20
gen, pe = [], []
for line in sys.stdin:
    r = re.search(r'([\d.]+) tokens per second', line)
    t = re.search(r'/\s+(\d+) tokens', line)
    if not (r and t): continue
    rate, ntok = float(r.group(1)), int(t.group(1))
    if 'prompt eval time' in line:
        pe.append(rate)
    elif ntok >= MIN_TOK:
        gen.append(rate)
if gen:
    print(f'  generation:  n={len(gen)} min={min(gen):.1f} max={max(gen):.1f} mean={sum(gen)/len(gen):.1f} tok/s  (gens >= {MIN_TOK} tok)')
else:
    print('  generation:  no samples found')
if pe:
    print(f'  prompt-eval: n={len(pe)} mean={sum(pe)/len(pe):.0f} tok/s')
" | tee -a "$REPORT"

{
  echo
  echo "--- Quality gate (independent verification) ---"
} | tee -a "$REPORT"

if [ -f "$PROJ/pyproject.toml" ]; then
  T=$(cd "$PROJ" && uv run pytest -q 2>&1 | tail -3 | tr '\n' ' ')
  R=$(cd "$PROJ" && uv run ruff check . 2>&1 | tail -2 | tr '\n' ' ')
  echo "  pytest: $T" | tee -a "$REPORT"
  echo "  ruff:   $R" | tee -a "$REPORT"
else
  echo "  no pyproject.toml — build did not complete" | tee -a "$REPORT"
fi

{
  echo "  files:  $(find "$PROJ" -name '*.py' -not -path '*/.venv/*' -not -path '*__pycache__*' | wc -l | tr -d ' ') python, README=$([ -s "$PROJ/README.md" ] && echo yes || echo NO), DESIGN=$([ -s "$PROJ/docs/DESIGN.md" ] && echo yes || echo NO)"
} | tee -a "$REPORT"

echo
echo "report written to $REPORT"
exit $EXIT

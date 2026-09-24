# Shared helpers for the rpi-coder-cli tests. Source from the other scripts.
# Every harness is pointed at logproxy.py (127.0.0.1:18080) so each request's prompt size,
# tool calls, malformed args and HTTP errors are logged, independent of what the agent reports.
export PATH="$HOME/.local/bin:$PATH"
[ -f ~/.config/local-llm.env ] && . ~/.config/local-llm.env
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROXY=http://127.0.0.1:18080
UNITTEST="python3 -m unittest discover -s tests -t ."
ROOT=~/harness-tests

proxy_start() {  # proxy_start <logfile>
  : > "$1"; PROXY_LOG="$1" python3 "$HERE/logproxy.py" 2>/dev/null & PROXY_PID=$!
  for _ in 1 2 3 4 5 6 7 8 9 10; do curl -s -o /dev/null $PROXY/health && return; sleep 0.5; done
}
proxy_stop() { kill "$PROXY_PID" 2>/dev/null; wait "$PROXY_PID" 2>/dev/null; }

# agent <harness> <prompt> [session-name]  — one non-interactive turn in the current dir.
# AIDER_EXTRA: extra aider flags, e.g. AIDER_EXTRA="--edit-format diff".
# Aider: all tracked text files are put in the chat (it can only edit files it's been given), it runs
#        the unit tests itself after each edit (--auto-test) and restores chat history between turns.
# Goose: named session; turn 2+ resumes it.
# Claude Code: via ~/.local/bin/claude-mac; turn 2+ uses -c.
agent() {
  local h=$1 p=$2 s=${3:-}
  case $h in
    aider)
      # shellcheck disable=SC2046
      aider --openai-api-base $PROXY/v1 --yes-always --no-stream --no-pretty \
            --restore-chat-history --test-cmd "$UNITTEST" --auto-test ${AIDER_EXTRA:-} \
            --message "$p" $(git ls-files '*.py' '*.md' 2>/dev/null) ;;
    goose)
      local a=(--no-session)
      if [ -n "$s" ]; then a=(-n "$s"); goose session list 2>/dev/null | grep -q -- "$s" && a+=(-r); fi
      OPENAI_HOST=$PROXY goose run "${a[@]}" -t "$p" ;;
    claude)
      # claude-mac wrapper, pointed at the logging proxy. The first call in a directory starts a session;
      # later calls continue the most recent one there (-c), like Goose -r / Aider --restore-chat-history.
      local c=(); [ -e .claude-turn ] && c=(-c); touch .claude-turn
      LOCAL_LLM_BASE=$PROXY claude-mac "${c[@]}" -p "$p" --dangerously-skip-permissions ;;
  esac
}

# unittest result, checked by us: "<passed>/<ran>" or "ERR"
check_tests() {
  # unittest's summary goes to stderr; stdout is dropped because code under test may print
  # after it (stdout is flushed at exit), which would push "Ran N tests" out of the tail.
  local out; out=$($UNITTEST 2>&1 >/dev/null | tail -3)
  local ran; ran=$(printf '%s' "$out" | sed -n 's/^Ran \([0-9]*\) test.*/\1/p')
  if printf '%s' "$out" | grep -q '^OK'; then echo "${ran}/${ran}"
  elif [ -n "$ran" ]; then echo "FAIL(${ran} ran)"; else echo "ERR"; fi
}

# summarise a proxy log: requests, peak prompt tokens, errors, malformed tool args
proxy_summary() {
  python3 - "$1" <<'PY'
import json,sys
rs=[json.loads(l) for l in open(sys.argv[1]) if l.strip()]
rs=[r for r in rs if 'completions' in r.get('path','') or '/v1/messages' in r.get('path','')]
pt=[(r.get('usage') or {}).get('prompt_tokens',0) for r in rs]
errs=[r for r in rs if r.get('status',200)>=400 or r.get('err')]
print(f"requests={len(rs)} peak_prompt={max(pt or [0])} tool_calls={sum(len(r.get('calls') or []) for r in rs)} "
      f"bad_args={sum(r.get('bad_args',0) for r in rs)} errors={len(errs)}"
      + (f" first_err={str(errs[0].get('err'))[:160]!r}" if errs else ""))
PY
}

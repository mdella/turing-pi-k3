#!/usr/bin/env bash
#
# check-ollama-release.sh — has a stable Ollama newer than 0.32.13 shipped yet?
#
#   ./check-ollama-release.sh          # prints STATUS line, exit 0 = new release
#
# WHY THIS EXISTS
# The taskcli three-way benchmark (qwen3.6 vs qwen3.8 GGUF vs qwen3.8 MLX) is
# blocked on Ollama 0.32.13, whose qwen renderer 500s on ~3% of /v1/messages
# calls and kills multi-turn agent runs mid-build. Fixed by 87abaa019
# "renderers/qwen: tolerate non-leading system messages", first tagged
# v0.32.14-rc0 on 2026-08-15. This watches for the STABLE release of that fix.
#
# Checks two independent sources, because they move at different times:
#   github  — the release is tagged and marked non-prerelease
#   brew    — the formula has been bumped, which is what actually lets jax run
#             `brew upgrade ollama` on this box
# Both must be reported; the benchmark needs brew, not just the tag.
#
# Deliberately does NOT match prereleases: an -rc tag is not something to
# upgrade a shared daemon to.
#
set -uo pipefail

BASELINE="0.32.13"
PY=/Users/mdella/projects/ComfyUI/.venv/bin/python

newest_stable="$(curl -fsS -m 25 "https://api.github.com/repos/ollama/ollama/releases?per_page=15" 2>/dev/null |
  "$PY" -c '
import json,sys,re
try: rs=json.load(sys.stdin)
except Exception: sys.exit(0)
for r in rs:
    if r.get("prerelease") or r.get("draft"): continue
    t=(r.get("tag_name") or "").lstrip("v")
    if re.fullmatch(r"\d+\.\d+\.\d+", t):
        print(t, (r.get("published_at") or "")[:10]); break
' 2>/dev/null)"

brew_ver="$(curl -fsS -m 25 https://formulae.brew.sh/api/formula/ollama.json 2>/dev/null |
  "$PY" -c 'import json,sys; print(json.load(sys.stdin)["versions"]["stable"])' 2>/dev/null)"

srv_ver="$(curl -fsS -m 10 http://localhost:11434/api/version 2>/dev/null |
  sed -n 's/.*"version":"\([^"]*\)".*/\1/p')"

gh_ver="${newest_stable%% *}"
gh_date="${newest_stable#* }"

# sort -V puts the greater version last; equal means not newer
newer() {  # newer <candidate> <baseline>
  [ -n "$1" ] && [ "$1" != "$2" ] &&
  [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | tail -1)" = "$1" ]
}

echo "  github stable : ${gh_ver:-unknown} ${gh_date:-}"
echo "  brew formula  : ${brew_ver:-unknown}"
echo "  this box      : ${srv_ver:-unreachable}"

# THE TRIGGER IS BREW, NOT THE GITHUB TAG.
# 0.32.14 was tagged 2026-08-15 while the formula sat at 0.32.13, so a check
# that fires on "either source moved" would have alerted on every single poll
# from then on while nothing actionable had changed. This box is upgraded with
# `brew upgrade ollama`; until the formula moves there is nothing to do, so the
# tag-only state is reported and deliberately does NOT exit 0.
#
#   0  BREW-READY   formula bumped -> jax can upgrade -> benchmark unblocked
#   2  TAGGED-ONLY  released upstream but not packaged yet -> stay quiet
#   1  NONE         nothing newer than the baseline at all
if newer "${brew_ver:-}" "$BASELINE"; then
  echo "STATUS: BREW-READY  brew=${brew_ver} github=${gh_ver:-?} (baseline $BASELINE)"
  echo "  jax can run: brew upgrade ollama && sudo launchctl kickstart -k system/com.ollama.serve"
  exit 0
fi

if newer "${gh_ver:-}" "$BASELINE"; then
  echo "STATUS: TAGGED-ONLY  github=${gh_ver} but brew still ${brew_ver:-?} — nothing to do yet"
  exit 2
fi

echo "STATUS: NONE  still $BASELINE"
exit 1

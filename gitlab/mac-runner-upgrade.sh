#!/bin/bash
# Upgrade both GitLab runners on the Mac Studio (see README "Mac Studio runners") to a given version.
#   mac-studio-docker: runs as mdella,     binary ~/gitlab-runner/bin/gitlab-runner
#   mac-studio-ci:     runs as gitlab-ci,  binary /Users/gitlab-ci/gitlab-runner/bin/gitlab-runner  (needs sudo)
# Usage (on the Mac, as mdella):  bash mac-runner-upgrade.sh v19.4.3
# Downloads the official darwin-arm64 binary, checks it against GitLab's release.sha256, keeps the old binary as
# gitlab-runner.<old version>, then sends SIGQUIT (graceful: a running job finishes first) and lets the LaunchDaemons'
# KeepAlive restart each runner on the new binary.
set -euo pipefail
VER="${1:?usage: $0 vX.Y.Z}"
BASE="https://gitlab-runner-downloads.s3.amazonaws.com/${VER}"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

echo "== downloading ${VER} (darwin-arm64) and its checksums"
curl -fsSL -o "$TMP/gitlab-runner" "$BASE/binaries/gitlab-runner-darwin-arm64"
curl -fsSL -o "$TMP/release.sha256" "$BASE/release.sha256"
want=$(awk '$2 ~ /binaries\/gitlab-runner-darwin-arm64$/ {print $1}' "$TMP/release.sha256")
have=$(shasum -a 256 "$TMP/gitlab-runner" | awk '{print $1}')
[ -n "$want" ] && [ "$want" = "$have" ] || { echo "CHECKSUM MISMATCH (want ${want:-none}, have $have) - aborting"; exit 1; }
chmod 755 "$TMP/gitlab-runner"
new=$("$TMP/gitlab-runner" --version | awk '/^Version:/{print $2}')
echo "   sha256 ok, binary reports $new"

swap() {   # $1 = owner, $2 = binary path, $3 = command prefix ("" or "sudo")
  local owner=$1 bin=$2 pre=$3 old
  old=$($pre "$bin" --version 2>/dev/null | awk '/^Version:/{print $2}')
  if [ "$old" = "$new" ]; then echo "== $owner: already $new"; return; fi
  echo "== $owner: $old -> $new"
  $pre cp -p "$bin" "$bin.$old"
  $pre install -m 755 "$TMP/gitlab-runner" "$bin.new"
  [ "$owner" = gitlab-ci ] && $pre chown gitlab-ci "$bin.new"
  $pre mv -f "$bin.new" "$bin"
  pid=$(pgrep -u "$owner" -f "gitlab-runner run" | head -1 || true)
  if [ -n "$pid" ]; then
    echo "   SIGQUIT to pid $pid (graceful; waits for a running job)"; $pre kill -QUIT "$pid"
  else
    echo "   no running process found for $owner - check the LaunchDaemon"
  fi
}

swap mdella   "$HOME/gitlab-runner/bin/gitlab-runner" ""
swap gitlab-ci "/Users/gitlab-ci/gitlab-runner/bin/gitlab-runner" "sudo"

echo "== waiting for the LaunchDaemons to restart both runners"
for i in $(seq 1 60); do
  a=$(pgrep -u mdella -f "gitlab-runner run" | head -1 || true); b=$(pgrep -u gitlab-ci -f "gitlab-runner run" | head -1 || true)
  [ -n "$a" ] && [ -n "$b" ] && break; sleep 5
done
echo "   mdella pid: ${a:-NOT RUNNING}   gitlab-ci pid: ${b:-NOT RUNNING}"
# 2026-10-30: the gitlab-ci runner's LaunchDaemon did not restart it after the graceful stop (a SIGQUIT exit is a
# clean exit, which KeepAlive/SuccessfulExit=false ignores), so start it explicitly if it is not back.
if [ -z "${b:-}" ]; then
  echo "   gitlab-ci runner did not come back: kickstarting system/com.mdella.gitlab-runner-ci"
  sudo launchctl kickstart -k system/com.mdella.gitlab-runner-ci; sleep 5
  b=$(pgrep -u gitlab-ci -f "gitlab-runner run" | head -1 || true); echo "   gitlab-ci pid: ${b:-STILL NOT RUNNING}"
fi
[ -n "${a:-}" ] || echo "   mdella runner did not come back: check its LaunchDaemon (sudo launchctl list | grep -i gitlab)"
echo "== verify"
"$HOME/gitlab-runner/bin/gitlab-runner" --version | head -2
"$HOME/gitlab-runner/bin/gitlab-runner" verify -c "$HOME/gitlab-runner/config.toml" 2>&1 | grep -E "is valid|ERROR" || true
sudo -u gitlab-ci /Users/gitlab-ci/gitlab-runner/bin/gitlab-runner verify -c /Users/gitlab-ci/gitlab-runner/config.toml 2>&1 | grep -E "is valid|ERROR" || true

#!/bin/bash
# Replace the Anthropic setup token (sk-ant-oat01-…, from `claude setup-token`) that Mickey, Cheshire and Luna share,
# then restart the gateway. Symptom it fixes: gateway log "401 … OAuth access token has been revoked".
# The token is read silently and passed on stdin — never in argv, chat or shell history.
# Usage (k3-node1): hermes/k8s/reauth-anthropic.sh     FORCE=1 skips the delivery-ledger check before the restart.
set -euo pipefail
G="kubectl -n hermes exec -i deploy/hermes -c gateway --"
read -rsp "New Anthropic setup token (sk-ant-oat01-…): " TOKEN; echo
[[ $TOKEN =~ ^sk-ant-oat01-[A-Za-z0-9_-]{20,}$ ]] || { echo "doesn't look like a setup token (sk-ant-oat01-…)"; exit 1; }

# Check the token works before touching anything (1-token request).
printf '%s' "$TOKEN" | $G python3 -c '
import sys, json, urllib.request, urllib.error
t = sys.stdin.read().strip()
r = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps({"model": "claude-haiku-5-5",
    "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]}).encode(), headers={"Authorization": "Bearer " + t,
    "anthropic-version": "2023-06-01", "anthropic-beta": "oauth-2025-04-20", "content-type": "application/json"})
try:
    urllib.request.urlopen(r, timeout=30); print("token works")
except urllib.error.HTTPError as e:
    msg = "HTTP %d %s" % (e.code, e.read()[:200].decode("utf-8", "replace"))
    if e.code == 401: sys.exit("token rejected: " + msg)
    print("token accepted, but the test call failed (continuing): " + msg)'

# Swap the ANTHROPIC_API_KEY line in all three .env files (atomic rename, permissions kept).
printf '%s' "$TOKEN" | $G python3 -c '
import os, re, sys, stat, tempfile
t = sys.stdin.read().strip(); h = os.environ["HERMES_HOME"]
for f in (h + "/.env", h + "/profiles/cheshire/.env", h + "/profiles/luna/.env"):
    s = open(f).read()
    n, k = re.subn(r"(?m)^ANTHROPIC_API_KEY=.*$", lambda _: "ANTHROPIC_API_KEY=" + t, s)
    if k != 1: sys.exit("%s: expected one ANTHROPIC_API_KEY= line, found %d" % (f, k))
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(f)); os.write(fd, n.encode()); os.close(fd)
    os.chmod(tmp, stat.S_IMODE(os.stat(f).st_mode)); os.replace(tmp, f); print("updated", f.replace(h, "~/.hermes"))'
unset TOKEN

# Restart only if no Signal message is waiting to be delivered (same check as runbooks/cluster-move/move-prep.sh).
PENDING=$($G python3 -c "
import sqlite3,os;c=sqlite3.connect(os.path.expanduser('~/.hermes/state.db'))
print(c.execute(\"select state,count(*) from delivery_obligations group by state\").fetchall())")
echo "delivery ledger: $PENDING"
if echo "$PENDING" | grep -qvE "^\[(\('(delivered|failed|abandoned|expired)', [0-9]+\)(, )?)*\]$" && [ "${FORCE:-0}" != 1 ]; then
  echo "undelivered messages — token saved, but NOT restarting. Re-run later or FORCE=1."; exit 1; fi
kubectl -n hermes rollout restart deploy/hermes && kubectl -n hermes rollout status deploy/hermes --timeout=300s
$G hermes auth list anthropic 2>&1 | sed -E 's/(sk-ant-[a-z0-9]+-)[A-Za-z0-9_-]+/\1…/g'

#!/usr/bin/env bash
# Test 6 — cold wake. ./t6-wake.sh <aider|goose>
# Waits (up to 30 min) for the coder to report is_sleeping, then times one trivial request.
. "$(dirname "$0")/lib.sh"; H=$1; D=$ROOT/t6-$H
sleeping() { curl -s -m 5 "$LOCAL_LLM_BASE/props" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("is_sleeping"))' 2>/dev/null; }
for _ in $(seq 1 180); do [ "$(sleeping)" = True ] && break; sleep 10; done
st=$(sleeping); rm -rf "$D"; mkdir -p "$D"; cd "$D" || exit 1; git init -q
proxy_start "$D/proxy.jsonl"   # agent() routes through the logging proxy, so it must be running
s=$(date +%s.%N); agent "$H" "What is 17*23? Answer with just the number." > agent.log 2>&1; rc=$?
w=$(python3 -c "print(round($(date +%s.%N)-$s,1))")
proxy_stop
echo "T6 $H sleeping_before=$st rc=$rc wall=${w}s answer_391=$(grep -c 391 agent.log)"

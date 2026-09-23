#!/usr/bin/env bash
# Test 7 — shared load. ./t7-load.sh <aider|goose> <sessions>   (1, 2 or 4 at once)
# Same one-shot task in N separate repos started together; slot-poll.py samples /slots every 2 s.
. "$(dirname "$0")/lib.sh"; H=$1; N=$2; B=$ROOT/t7-$H-$N
rm -rf "$B"; mkdir -p "$B"
P="Create textstats.py with functions word_count(text), char_count(text, include_spaces=True) and top_words(text, n) returning a list of (word, count) tuples sorted by count descending then word ascending, words lower-cased. Create tests/__init__.py and unittest tests in tests/test_textstats.py. Then run: $UNITTEST  and fix anything that fails."
python3 "$HERE/slot-poll.py" "$B/poll.jsonl" & POLL=$!
proxy_start "$B/proxy.jsonl"
for k in $(seq 1 "$N"); do
  ( mkdir -p "$B/$k"; cd "$B/$k" && git init -q && git -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
    s=$(date +%s); agent "$H" "$P" "t7-$H-$N-$k-$(date +%s)" > agent.log 2>&1; rc=$?
    echo "  session $k rc=$rc wall=$(( $(date +%s)-s ))s tests=$(check_tests)" ) &
done
wait $(jobs -p | grep -v -e "$POLL" -e "$PROXY_PID")
proxy_stop; kill $POLL 2>/dev/null
python3 - "$B/poll.jsonl" "$N" "$H" <<'PY'
import json,sys
rs=[json.loads(l) for l in open(sys.argv[1]) if l.strip() and 'err' not in l]
busy=[len(r['busy']) for r in rs]; rates=[v for r in rs for v in r['rates'].values()]
agg=[sum(r['rates'].values()) for r in rs if r['rates']]
print(f"T7 {sys.argv[3]} x{sys.argv[2]}: samples={len(rs)} max_busy_slots={max(busy or [0])} "
      f"per_slot_decode_mean={sum(rates)/len(rates) if rates else 0:.0f} t/s aggregate_mean={sum(agg)/len(agg) if agg else 0:.0f} t/s")
PY
echo "  $(proxy_summary "$B/proxy.jsonl")"

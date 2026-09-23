#!/usr/bin/env bash
# Test 5 — 16-turn session building one todo CLI. ./t5-long.sh <aider|goose>
# Per turn: exit code, wall time, our own unittest run, and the proxy's peak prompt / errors for that turn.
. "$(dirname "$0")/lib.sh"; H=$1; D=$ROOT/t5-$H; S="t5-$H-$(date +%s)"
rm -rf "$D"; mkdir -p "$D"; cd "$D" || exit 1; git init -q
git -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
T=" Then run: $UNITTEST  and fix anything that fails."
TURNS=(
 "Create a Python package todo/ with todo/store.py containing class TodoStore. The constructor takes the path of a JSON file used for storage. Add method add(self, title) that stores a new open todo and returns its new integer id (1, 2, 3...). Create tests/__init__.py and unittest tests in tests/test_store.py.$T"
 "Add TodoStore.list_items(include_done=False) returning the todos as dicts with id, title and done.$T"
 "Add TodoStore.mark_done(todo_id). It must raise KeyError for an unknown id.$T"
 "Add TodoStore.delete(todo_id), also raising KeyError for an unknown id.$T"
 "Create todo/cli.py with a main(argv=None) function using argparse, with subcommands add, list, done and delete that use TodoStore. Add a --db option (default todo.json) for the storage path.$T"
 "Add unittest tests for the CLI in tests/test_cli.py that call main([...]) with a temporary --db file.$T"
 "Add a priority field (low, normal or high; default normal) to todos. TodoStore.add gets a priority parameter and the CLI add command gets a --priority option.$T"
 "Make list output sorted by priority (high first) then by id.$T"
 "Add an optional due date (YYYY-MM-DD) to todos. Validate the format and raise ValueError on bad input. The CLI add command gets a --due option.$T"
 "Add an overdue subcommand that lists open todos whose due date is before today.$T"
 "Without changing any code, list every file in this project and summarise in one line what each contains."
 "Refactor: move the JSON loading and saving out of TodoStore into a new todo/storage.py with a JsonStorage class, and make TodoStore use it. Behaviour must not change.$T"
 "If the JSON storage file is corrupt, raise a clear error; the CLI must print a one-line error message and exit with status 1 instead of a traceback. Add a test for this.$T"
 "Add a search subcommand that lists todos whose title contains the given text, case-insensitive.$T"
 "Write README.md documenting installation and every CLI subcommand with an example.$T"
 "Without looking at the files, answer from memory: in the very first request of this session, what exact method signature did you create on TodoStore?"
)
echo "T5 $H session=$S"
for i in "${!TURNS[@]}"; do
  n=$((i+1)); proxy_start "$D/proxy-$n.jsonl"
  s=$(date +%s); agent "$H" "${TURNS[$i]}" "$S" > "$D/turn-$n.log" 2>&1; rc=$?; w=$(( $(date +%s)-s ))
  proxy_stop
  echo "turn $n rc=$rc wall=${w}s tests=$(check_tests) $(proxy_summary "$D/proxy-$n.jsonl")"
done
echo "--- turn 16 answer (expected: add(self, title)):"; tail -15 "$D/turn-16.log"
echo "--- final: $(ls todo tests 2>/dev/null | tr '\n' ' ') README_lines=$(wc -l < README.md 2>/dev/null) tests=$(check_tests)"

#!/usr/bin/env bash
#
# run-chunk.sh — one pass of the comparison (1 build per model), archived under
# its own chunk number.
#
#   ./run-chunk.sh 1   # -> chunk-1.json
#
# WHY CHUNKS
# The full `./run-comparison.sh 3` round takes ~4 h and was terminated three
# times at different points (mid-build, after 1 build, after 2 builds). Because
# run-comparison.sh rewrites comparison-results.json from scratch there is no
# resume, so every kill cost the entire round. One pass is ~45-60 min, and the
# archive happens inside this script, so an interrupted chunk loses only itself.
#
# Merge the chunks with merge-chunks.py, which relabels the run index -- every
# chunk reports run=1 internally, so they would otherwise collide.
set -uo pipefail
N="${1:?usage: run-chunk.sh <chunk-number>}"
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE" || exit 1

./run-comparison.sh 1
rc=$?

if [ -s comparison-results.json ]; then
  cp comparison-results.json "chunk-$N.json"
  echo "archived -> chunk-$N.json"
else
  echo "chunk $N produced no results" >&2
fi
exit $rc

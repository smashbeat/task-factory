#!/bin/bash
# Replay an agent's saved program on hidden packages, offline, the way the verifier runs it, and diff each
# output against the generator's truth. A miss that replays is a miss you can read from the program.
# usage: scripts/trials/replay_agent.sh TRIAL_DIR BUILD_DIR ID...
#   TRIAL_DIR  a Harbor trial folder (…/jobs/<job>/<task>__<id>); its artifacts/app/intake is the program
#   BUILD_DIR  the build the task came from (out/build-lot-1b): pkg/, specs/ and truth/ live there
#   ID...      hidden item ids (h09 h11 …)
# Defaults are the lot-release pack's; set IMAGE, TOOL and PKG_EXT for another pack.
# Output: out/replay/<job>/ID.{json,stdout,stderr}. Harbor's [REDACTED] marks are undone in the copied program.
set -u
T=$(cd "$1" && pwd) || exit 1
B=$(cd "$2" && pwd) || exit 1
shift 2
R=$(cd "$(dirname "$0")/../.." && pwd)
IMAGE=${IMAGE:-tf-lot-release-ref:latest}
TOOL=${TOOL:-/app/intake/intake.py}
PKG_EXT=${PKG_EXT:-pkg}
LIMIT=${LIMIT:-300}
NAME=$(basename "$(dirname "$T")")
PROG="$R/out/replay/$NAME/program"
OUT="$R/out/replay/$NAME"
mkdir -p "$OUT"
if [ ! -d "$PROG" ]; then
  mkdir -p "$PROG"
  (cd "$T/artifacts/app/intake" && find . -type f -not -path '*/.git/*' -not -name '*.pyc') | while read -r f; do
    mkdir -p "$PROG/$(dirname "$f")"
    sed 's/\[REDACTED\]/1/g' "$T/artifacts/app/intake/$f" > "$PROG/$f"
  done
fi
for ID in "$@"; do
  docker run --rm --network none --cpus 2 -e OMP_THREAD_LIMIT=1 \
    -v "$PROG:/app/intake:ro" -v "$B/pkg:/pkg:ro" -v "$B/specs:/specs:ro" -v "$OUT:/out" \
    "$IMAGE" bash -c "cd /tmp && time timeout --signal=KILL $LIMIT python3 $TOOL /pkg/$ID.$PKG_EXT /specs/$ID.json /out/$ID.json" \
    > "$OUT/$ID.stdout" 2> "$OUT/$ID.stderr"
  rc=$?
  res=$(cd "$R/packs/lot-release/task/tests" && python3 -I -c "
import sys; sys.path.insert(0, '.'); import compare
d = compare.compare_files('$OUT/$ID.json', '$B/truth/$ID.json')
print('PASS' if not d else 'FAIL'); [print('  ', x[:220]) for x in d[:8]]" 2>&1)
  echo "$ID rc=$rc $(grep real "$OUT/$ID.stderr" | tr -d '\t')"
  echo "$res"
done

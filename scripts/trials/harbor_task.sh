#!/bin/bash
# Run one Harbor job on a task directory and print its reward, test summary, exception type and failed items.
# usage: scripts/trials/harbor_task.sh TASK_DIR JOBS_DIR JOB_NAME [harbor agent args...]
#   No agent args means the oracle: Harbor runs the task's own solution.
#   Examples of agent args:
#     --agent nop
#     --agent claude-code -m anthropic/claude-sonnet-5-5 --ak reasoning_effort=max --ae CLAUDE_FORCE_OAUTH=1 \
#         --ae "CLAUDE_CODE_OAUTH_TOKEN=$CLAUDE_CODE_OAUTH_TOKEN" --timeout-multiplier 0.25
# Harbor writes every digit 1 as [REDACTED] in the trial's files when an env value passed with --ae is "1",
# so the summaries below undo that before reading.
set -u
T=$(cd "$1" && pwd) || exit 1
J=$(cd "$2" && pwd) || exit 1
NAME=$3
shift 3
harbor run -p "$T" "$@" --env docker -o "$J" --job-name "$NAME" --yes > "$J/$NAME.console.log" 2>&1
t=$(ls -d "$J/$NAME"/*__* 2>/dev/null | head -1)
if [ -z "$t" ]; then
  echo "$NAME: no trial directory; console tail:"
  tail -5 "$J/$NAME.console.log" | cut -c1-200
  exit 1
fi
unredact() { sed 's/\[REDACTED\]/1/g' "$1" 2>/dev/null; }
echo "$NAME reward=$(unredact "$t/verifier/reward.txt" || echo none) | $(unredact "$t/verifier/test-stdout.txt" | grep -E '[0-9]+ (passed|failed)' | tail -1)"
unredact "$t/result.json" | python3 -c "
import json, sys
r = json.load(sys.stdin); e = r.get('exception_info'); a = r.get('agent_result') or {}
print('  exception:', e.get('exception_type') if isinstance(e, dict) else e,
      '| started', (r.get('started_at') or '')[11:19], 'finished', (r.get('finished_at') or '')[11:19],
      '| cost', a.get('cost_usd'))"
unredact "$t/verifier/test-stdout.txt" | grep -E '^FAILED' | sed -E 's/.*test_([a-z0-9]+).*/\1/' | tr '\n' ' '
echo

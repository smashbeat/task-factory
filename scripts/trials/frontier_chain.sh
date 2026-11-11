#!/bin/bash
# One frontier trial per model family, run one after the other: never two heavy Docker jobs at once,
# because the verifier's time limit per item is wall-clock on two CPUs.
# usage: scripts/trials/frontier_chain.sh TASK_DIR JOBS_DIR CODEX_JOB OPUS_JOB
# needs: `codex login` done on this machine, and CLAUDE_CODE_OAUTH_TOKEN exported (from `claude setup-token`).
# Summary lines go to JOBS_DIR/frontier-chain.log. The token is read from the environment only.
set -u
: "${CLAUDE_CODE_OAUTH_TOKEN:?export CLAUDE_CODE_OAUTH_TOKEN first}"
HERE=$(cd "$(dirname "$0")" && pwd)
T=$1; J=$2; CODEX=$3; OPUS=$4
L="$J/frontier-chain.log"
echo "$(date -u +%FT%TZ) start codex $CODEX" >> "$L"
bash "$HERE/harbor_task.sh" "$T" "$J" "$CODEX" \
  --agent codex -m openai/gpt-6.1-sol --ak reasoning_effort=xhigh --ae CODEX_FORCE_AUTH_JSON=1 >> "$L" 2>&1
echo "$(date -u +%FT%TZ) codex done; containers left: $(docker ps -q | wc -l | tr -d ' ')" >> "$L"
echo "$(date -u +%FT%TZ) start opus $OPUS" >> "$L"
bash "$HERE/harbor_task.sh" "$T" "$J" "$OPUS" \
  --agent claude-code -m anthropic/claude-opus-5-5 --ak reasoning_effort=max \
  --ae CLAUDE_FORCE_OAUTH=1 --ae "CLAUDE_CODE_OAUTH_TOKEN=$CLAUDE_CODE_OAUTH_TOKEN" \
  --ae CLAUDE_CODE_MAX_OUTPUT_TOKENS=128000 >> "$L" 2>&1
echo "$(date -u +%FT%TZ) opus done; containers left: $(docker ps -q | wc -l | tr -d ' ')" >> "$L"

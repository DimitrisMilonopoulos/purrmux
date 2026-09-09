#!/usr/bin/env bash
set -u

# Reports an agent's state into kitty user vars, which the tab bar renders:
#   agent_status     working | blocked | done | idle  (drawn under agent tabs)
#   agent_attention  1 while the agent wants you and you are looking elsewhere
# Modes match those status names; "set" and "clear" are kept as aliases so an
# older settings.json registration keeps working. Claude Code and Codex both
# call this — their hook events line up — so the caller names itself in $2.
mode="${1:-set}"
agent="${2:-claude}"
window_id="${KITTY_WINDOW_ID:-}"

if [ -z "$window_id" ] || ! command -v kitten >/dev/null 2>&1; then
  exit 0
fi

match="id:$window_id"

case "$mode" in
  blocked | set) status=blocked; attention=1 ;;
  done) status=done; attention=1 ;;
  working) status=working; attention=0 ;;
  idle) status=idle; attention=0 ;;
  clear) status=''; attention=0 ;;
  *) exit 0 ;;
esac

# Attention is about windows you are not watching; the status is set either way.
if [ "$attention" = 1 ] &&
  kitten @ ls --match "$match and state:focused and state:parent_focused" >/dev/null 2>&1; then
  attention=0
fi

now=$(date +%s 2>/dev/null || printf '0')

# A bare name deletes the variable, name=value sets it. agent_status_at is when
# the status was last reported, which the overview shows as its age — for
# one-shot events (blocked, done) that is the transition, and while working it
# doubles as a heartbeat.
if [ -n "$status" ]; then
  vars=(agent_status="$status" agent_name="$agent" agent_status_at="$now")
else
  vars=(agent_status agent_name agent_status_at)
fi

if [ "$attention" = 1 ]; then
  vars+=(agent_attention=1 agent_attention_source="$mode" agent_attention_at="$now")
else
  vars+=(agent_attention agent_attention_source agent_attention_at)
fi

kitten @ set-user-vars --match "$match" "${vars[@]}" >/dev/null 2>&1 || true

exit 0

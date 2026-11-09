#!/bin/sh
# Claude Code hook (PostToolUse on every tool, UserPromptSubmit): tell Claude about task changes
# the human made in the Herdr panel. Runs on every tool call, so it starts Python only when htask
# has written since this session last looked: the session's stamp holds the content of
# signal/changed (a fresh timestamp on every write) as it was then. Comparing content, not file
# times, matters: macOS's /bin/sh compares modification times to the whole second.
input=$(cat)
if [ -n "$HTASK_DB" ]; then dir=$(dirname "$HTASK_DB"); else dir="${XDG_DATA_HOME:-$HOME/.local/share}/herdr-tasks"; fi
session=$(printf '%s' "$input" | sed -n 's/.*"session_id" *: *"\([^"]*\)".*/\1/p' | head -n 1)
stamp="$dir/seen/${session:-unknown}"
current=$(cat "$dir/signal/changed" 2>/dev/null)
if [ -n "$session" ] && [ -e "$stamp" ] && [ "$current" = "$(cat "$stamp")" ]; then
  exit 0
fi
# Record what we've seen before reading: a write after this differs, so the next call looks again.
mkdir -p "$dir/seen" && printf '%s' "$current" > "$stamp"
htask="${HTASK_BIN:-$HOME/.local/bin/htask}"
printf '%s' "$input" | exec "$htask" hook claude-inbox

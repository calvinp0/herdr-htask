#!/bin/sh
# Claude Code hook (PostToolUse on every tool, UserPromptSubmit): tell Claude about task changes
# the human made in the Herdr panel. Runs on every tool call, so it starts Python only when htask
# has written since this session last looked (signal/changed newer than the session's stamp).
input=$(cat)
if [ -n "$HTASK_DB" ]; then dir=$(dirname "$HTASK_DB"); else dir="${XDG_DATA_HOME:-$HOME/.local/share}/herdr-tasks"; fi
session=$(printf '%s' "$input" | sed -n 's/.*"session_id" *: *"\([^"]*\)".*/\1/p' | head -n 1)
stamp="$dir/seen/${session:-unknown}"
if [ -n "$session" ] && [ -e "$stamp" ] && ! [ "$dir/signal/changed" -nt "$stamp" ]; then
  exit 0
fi
mkdir -p "$dir/seen" && touch "$stamp"
htask="${HTASK_BIN:-$HOME/.local/bin/htask}"
printf '%s' "$input" | exec "$htask" hook claude-inbox

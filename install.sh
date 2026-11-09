#!/bin/sh
# Install htask from this checkout, or re-point an existing install at it. Safe to re-run:
# run it again after moving or renaming this folder, and after `git pull` (the desktop-app mod
# is a copy, so it only changes when this copies it again).
#
# Everything else refers to ~/.local/bin, never to this folder: agents run `htask`, and the
# Claude Code hooks run ~/.local/bin/htask and ~/.local/bin/htask-claude-inbox.
set -eu

repo=$(cd "$(dirname "$0")" && pwd -P)
bin="$HOME/.local/bin"
mkdir -p "$bin"
ln -sfn "$repo/htask" "$bin/htask"
ln -sfn "$repo/hooks/claude-inbox.sh" "$bin/htask-claude-inbox"
echo "linked $bin/htask and $bin/htask-claude-inbox -> $repo"

# Herdr desktop app: copy the mod. The app reloads it live.
app="${HERDR_APP_HOME:-$HOME/.config/herdr-app}"
if [ -d "$app" ]; then
  mkdir -p "$app/mods/htask"
  for f in "$repo"/mods/htask/*; do
    cp "$f" "$app/mods/htask/"
  done
  echo "copied the desktop-app mod to $app/mods/htask"
  if command -v herdr-app >/dev/null 2>&1; then
    herdr-app check "$app/mods/htask"
  fi
fi

# Herdr terminal UI: link the plugin to this folder (unlinking first moves an old link).
if command -v herdr >/dev/null 2>&1; then
  herdr plugin unlink calvin.htask >/dev/null 2>&1 || true
  if herdr plugin link "$repo" >/dev/null 2>&1; then
    echo "linked the Herdr terminal-UI plugin to $repo"
  else
    echo "could not link the Herdr terminal-UI plugin (is a Herdr server running?)"
  fi
fi

echo
exec "$bin/htask" doctor

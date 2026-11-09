# Reference

## CLI

```sh
htask add "title" [-d "description"] [--after 3,4] [--from 31] [--status todo|doing|blocked|done|dropped]
htask start|done|drop|reopen <id>...      # reopen = back to to-do (also unblocks)
htask block <id> -m "what you need"
htask note <id> "text"
htask edit <id> [--title ...] [-d ...] [--from 31]    # --from 0 clears it
htask depend <id> --on 3 [--clear]        # this task comes after #3
htask next                                # the first to-do that isn't waiting on another
htask timeline [--limit 40] [--everywhere] [--json]   # who did what to which task, newest first
htask list [--all] [--archived] [--everywhere] [--json]   # --everywhere: every repo
htask archive <id>...                     # archive done/dropped tasks now
htask clean [--days 7] [--everywhere] [--dry-run]   # archive old done/dropped tasks
htask summary                             # JSON: counts here + blocked tasks everywhere
htask connect status|all|claude|codex|pi [--remove]   # set agents up (or take htask out)
htask doctor                              # check the install
htask update [--check]                    # git pull, re-install, refresh connected agents
htask panel                               # the terminal panel (curses)
```

- `start` claims the task for the terminal that runs it, so the panel shows that agent's state.
- `done` refuses a task whose dependencies aren't done; `--force` overrides. Starting early only warns.
- Global options: `--project <dir>` (default: the current git root) and `--by <who>`.
- `HTASK_DB` overrides the database path.

## Updating and moving

Nothing outside the checkout names it: agents run `htask`, and the hooks run links in `~/.local/bin`.

- **To update**, open the panel's **Agents** box and click **Check for updates**, then **Update**. It runs
  `htask update` on the machine of the space you're in. Or run `htask update` there yourself. It pulls,
  re-installs and refreshes the agents you've connected; `--check` only says if there's one.
- **On Windows**, `git pull` in your clone and copy `mods\htask` into the app's `mods` folder again.
- **Out of step?** The panel says so ("htask on <machine> is 0.1.0; this panel is 0.1.1") with a button
  to update htask there. A Windows panel older than htask needs its mod copied again.
- **After moving or renaming the folder**, run `./install.sh` from its new place.
- **`htask doctor`** checks the links, hooks, plugin and app mod, and says what to run if something's off.

If htask can't run, the status chip shows a red `htask ✗`.

## App: setting up the layout by hand

**Add to my layout** in the panel does this for you. Or ask the agent running in Herdr:
*"Read ~/.config/herdr-app/AGENTS.md, then add this mod: https://github.com/calvinp0/herdr-htask"*
(it follows [RECIPE.md](../RECIPE.md)). By hand, edit your own layout in
`~/.config/herdr-app/layouts/` (Herdr's own layouts are read-only; copy one with
`herdr-app do layout.clone '{"name":"main","as":"my-layout"}'`):

- **Panel:** add `{ "id": "htask", "type": "block", "content": { "mod": "htask" } }`, for example to
  the right-hand stack with Files and Changes.
- **Chip:** add to the status row
  `{ "id": "status-htask", "type": "block", "content": { "mod": "htask", "props": { "view": "chip" } }, "size": { "weight": 1.3 }, "min": 96 }`.
  It's needed for blocked-task toasts. Clicking it shows or hides the panel, wherever it is; with no
  panel block, it opens the panel as a floating window.
- **Tab-bar button (optional):** the chip publishes `shared("htask.summary")` =
  `{project, done, total, blocked}` for a `2/5` badge.

## App: keys

Bind these in `~/.config/herdr-app/keys.json`, for example `"global": { "ctrl-alt-t": "htask.toggle-todo" }`:

- `htask.toggle-todo`, `htask.toggle-done`, `htask.toggle-dropped`, `htask.toggle-archived`
- `htask.toggle-all` (this repo / every repo)
- `htask.dock` (Add to my layout), `htask.agents` (the Agents box), `htask.timeline`
- `htask.check-update`, `htask.update` (where the focused space runs)

## Remote spaces

A space on an SSH machine runs htask **on that machine**, against its own database. Install htask
there once (`./install.sh && htask connect all`). Remote spaces refresh every 5 seconds.

## Terminal UI

Bind a key in `~/.config/herdr/config.toml`, then run `herdr server reload-config`:

```toml
[[keys.command]]
key = "prefix+t"
type = "plugin_action"
command = "calvin.htask.open"
description = "open task panel"
```

Panel keys: `j`/`k` scroll, `t` to-do, `d` done, `x` dropped, `a` archived, `v` descriptions, `q` close.

For progress in the sidebar, add the `$tasks` token (done/total for the agent's repo):

```toml
[ui.sidebar.agents]
rows = [["state_icon", "machine", "workspace", "tab"], ["agent", "$tasks"]]

[ui.sidebar.spaces]
rows = [["state_icon", "workspace", "$tasks"], ["branch", "git_status"]]
```

## Data

One SQLite database at `~/.local/share/herdr-tasks/tasks.db`, in WAL mode so agents can write while
the panel reads. After each write htask rewrites `signal/changed` beside it, which the panel watches.

- `tasks`: one row per task. `project` is the repo root; `pane_id` is the terminal it came from
  (`t6` in the app, `w1:p2` in the terminal UI); `external_id` ties it to a Claude or Codex task.
- `from_id` on a task: the task it came out of (`--from`). Not an order; that's `deps`.
- `deps`: `task_id` comes after `depends_on`. A done or dropped dependency no longer holds it back.
- `changes`: who changed what, when, from which terminal (`by = 'you'` for the human). It feeds
  the timeline and the Claude inbox hook; changes copied in by the Claude and Codex hooks are logged too.
- `hook_cursor`: how far each Claude session has read `changes`.

Example: `sqlite3 ~/.local/share/herdr-tasks/tasks.db 'select status, count(*) from tasks group by 1'`

## Pictures

- `preview.png` is a real screenshot of the panel (the herdr.dev listing uses it too).
- `docs/hero.png` is an illustration, drawn in `docs/hero.html` with the panel's real colours and
  layout. After changing the panel, update the HTML and re-render it:

  ```sh
  google-chrome --headless=new --hide-scrollbars --force-device-scale-factor=2 --window-size=1600,1100 \
    --virtual-time-budget=8000 --screenshot=/tmp/hero.png "file://$PWD/docs/hero.html"
  # then crop to the top 3200x1800 pixels and save it as docs/hero.png
  ```

## Tests

```sh
python3 -m unittest discover tests
node --test tests/layout_edit.test.mjs
```

CI runs both on Linux and macOS (Python 3.10 and 3.12) and syntax-checks the mod with `node --check`.
`herdr-app check ~/.config/herdr-app/mods/htask` needs Herdr, so run it locally.

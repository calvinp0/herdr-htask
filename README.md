# htask: agent task panel for Herdr

A right-hand Herdr panel that shows what a coding agent has finished, what it is
doing, and what is left. Agents write tasks to a shared SQLite database with the
`htask` CLI. The panel follows whichever pane you focus and redraws as soon as
any agent writes.

```
herdr_todo
claude  w1:p1
███████████░░░░░░░░░░░░░░░░░ 1/4

DOING (1)
›◐ #1 Write parser for ORCA 6 output
      Handle the new energy block layout
      ↳ regex done for 6.0, 6.1 untested
BLOCKED (1)
 ✗ #2 Add tests for parser
      ↳ need sample outputs from cluster
DONE (1)
 ● #3 Update docs
```

`›` marks tasks created by the focused pane.

## Install

```sh
ln -s "$PWD/htask" ~/.local/bin/htask     # agents need it on PATH
```

### Herdr desktop app (`herdr-app`)

The app uses JavaScript mods, not the terminal UI's plugins. `herdr-app/mods/htask/` is a native
panel that shows the focused terminal's repo and redraws when `htask` writes.

```sh
cp -r herdr-app/mods/htask ~/.config/herdr-app/mods/
herdr-app check ~/.config/herdr-app/mods/htask
```

Then put it in your layout's right-hand panel stack and give it a button:

- in `~/.config/herdr-app/layouts/<layout>.json`, add
  `{ "id": "htask", "type": "block", "content": { "mod": "htask" } }` to the `panel-body` stack;
- in the tab bar mod (`tabs-plus/main.js`), add `["htask", "Tasks", "mods/htask/htask.svg"]` to
  `PANELS` and `"htask"` to the `enabled` list.

For the status-bar chip, add this to the `status` row (before `status-controls`):
`{ "id": "status-htask", "type": "block", "content": { "mod": "htask", "props": { "view": "chip" } }, "size": { "weight": 1.3 }, "min": 96 }`.
The chip shows `done/total` for the focused repo and how many tasks are blocked in any repo.
It raises a Herdr toast when a task becomes blocked (click it to jump to that agent's terminal),
and publishes `shared("htask.summary")` = `{project, done, total, blocked}`, which the tab bar's
Tasks button shows as `2/5` plus a red dot. The chip has to be in the layout for toasts and the
badge to work: the panel only starts once it has been opened.

Clicking **Tasks** in the tab bar opens and closes the panel. In the panel:

- click a task for its description, agent, last update and buttons (Start, Done, Unblock, Drop, Reopen);
- click a task's status dot to mark it done, or to reopen it;
- type in the box at the bottom and press Enter to add a task (recorded with agent `you`), so you
  can queue work for the next agent;
- tasks in progress or blocked show their agent's live state, for example `t6 working`. Click it to
  jump to that terminal. When the agent has exited or its terminal closed, the task says nobody is
  working on it. `htask` rewrites `~/.local/share/herdr-tasks/signal/changed` after every
change, and the panel watches that folder. It can't watch the DB folder itself, because SQLite
creates and deletes its `-wal`/`-shm` files on every read.

### Herdr terminal UI (`herdr`)

```sh
herdr plugin link "$PWD"
```

Add a key to `~/.config/herdr/config.toml`, then run `herdr server reload-config`:

```toml
[[keys.command]]
key = "prefix+t"
type = "plugin_action"
command = "calvin.htask.open"
description = "open task panel"
```

Panel keys: `j`/`k` scroll, `d` show or hide done tasks, `v` show or hide descriptions, `q` close.

#### Progress in the sidebar

When an agent in a Herdr TUI pane changes a task, htask sets a `$tasks` token (`done/total` for
that repo) on the agent's pane and workspace. Add the token to the sidebar rows in
`~/.config/herdr/config.toml`, then run `herdr server reload-config`:

```toml
[ui.sidebar.agents]
rows = [["state_icon", "machine", "workspace", "tab"], ["agent", "$tasks"]]

[ui.sidebar.spaces]
rows = [["state_icon", "workspace", "$tasks"], ["branch", "git_status"]]
```

## Claude Code: automatic, through a hook

Claude Code already plans with its own task tool. This hook copies `TaskCreate`/`TaskUpdate`
(and the older `TodoWrite`) into htask, keyed by session and Claude's task id, so the panel fills
without the agent doing anything. Add it to `~/.claude/settings.json`:

```json
"hooks": {
  "PostToolUse": [
    { "matcher": "TaskCreate|TaskUpdate|TodoWrite",
      "hooks": [ { "type": "command", "command": "~/.local/bin/htask hook claude", "timeout": 10 } ] }
  ]
}
```

The hook always exits 0, so a failure can never block a tool call. Errors go to stderr.

## Tell the agents to use it

Paste this into `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md`, or into a
project's own `CLAUDE.md`/`AGENTS.md`:

```markdown
## Task tracking (htask)

For any task with more than one step, record the plan with `htask` so it
shows in the Herdr task panel. Tasks are scoped to the current git repo.

- `htask list` to see open tasks first, so you pick up existing work
  instead of duplicating it.
- `htask add "<short title>" -d "<what done looks like>"` for each step.
- `htask start <id>` before working on a step, `htask done <id>` after verifying it.
- `htask note <id> "<progress, findings, next step>"` to leave information for the human.
- `htask block <id> -m "<what you need>"` when you are waiting on the user or something external.
- Keep using your own todo tool as well; htask is the record the human reads.
```

## Cleaning up

Done and dropped tasks stay until you archive them. Archived tasks leave the panel and the counts
but are kept:

```sh
htask clean                   # this repo: done/dropped more than 7 days ago
htask clean --days 0          # this repo: every done/dropped task (the panel's Archive button)
htask clean --everywhere      # every repo
htask clean --dry-run         # list what would be archived
htask list --archived         # see them; `htask reopen <id>` brings one back
```

## Remote machines (SSH spaces in the Herdr app)

When the focused space is on an SSH machine, the panel and chip run htask **on that machine**
(`exec` with `on`), against that machine's own DB. Install it there once:

```sh
scp htask <machine>:~/.local/bin/htask
```

Remote spaces are polled every 5 s instead of watched. Blocked tasks on a remote machine are
announced while one of its spaces is focused. This computer's blocked tasks are always announced.
The Claude hook and the agent instructions also need setting up on that machine if agents run
there.

## Data

- Database: `$HTASK_DB`, or `$XDG_DATA_HOME/herdr-tasks/tasks.db`
  (by default `~/.local/share/herdr-tasks/tasks.db`).
- One `tasks` table. `project` is the git root of the directory the command ran
  in. `agent` and `pane_id` are filled in automatically inside Herdr.
- WAL mode, so the panel can read while several agents write.
- Query it directly: `sqlite3 ~/.local/share/herdr-tasks/tasks.db 'select status, count(*) from tasks group by 1'`.

## Tests

```sh
python3 -m unittest discover tests
```

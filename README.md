# htask: a task panel for coding agents in Herdr

A side panel for [Herdr](https://herdr.dev) that shows what your coding agents have finished,
what they're working on, what's blocked, and what's left. Agents record tasks with a small
`htask` CLI in one shared SQLite database. The panel follows the terminal you focus, shows that
repo's tasks, and updates as soon as any agent writes.

<p align="center">
  <img src="docs/panel.png" width="420" alt="The Tasks panel in the Herdr desktop app: a blocked task with its reason, a task in progress, two to-do tasks and the five most recent done tasks, with a Tasks 8/12 button and a red dot in the tab bar">
</p>

The panel showing this repo's own tasks. The status bar gets a chip with the same count and how
many tasks are blocked across all repos: <img src="docs/chip.png" height="22" alt="Status-bar chip: 8/12, 5 blocked">

(The middle of the panel, which was empty, is cut out of the screenshot.)

It works with both Herdr front ends:

- **Herdr desktop app** (`herdr-app`): a native panel mod, a status-bar chip, a toast when a
  task becomes blocked, and a done/total badge on the panel's button.
- **Herdr terminal UI** (`herdr`): a plugin pane, plus a `$tasks` progress token for the sidebar.

## How it works

- **Agents write tasks** with `htask add`, `start`, `done`, `note` and `block`, or, for Claude Code,
  a hook copies Claude's own task list automatically. Tasks belong to the git repo the command
  ran in.
- **One database** at `~/.local/share/herdr-tasks/tasks.db` (WAL mode, so several agents can write
  while the panel reads). After every write htask rewrites `signal/changed` next to it, and the
  panel watches that.
- **You can change tasks too**, from the panel. The agent that owns the task is told: Claude
  through a hook at its next step, other agents with a message typed into their terminal.

## Requirements

- Python 3.10 or newer (standard library only)
- Herdr desktop app 0.1.14+ with herdr-core (`hc`), and/or the Herdr terminal UI 0.9+
- git (tasks are grouped by repo)

## Install the CLI

```sh
git clone https://github.com/calvinp0/herdr-htask
cd herdr-htask
ln -s "$PWD/htask" ~/.local/bin/htask     # agents need it on their PATH
```

## Herdr desktop app

Copy the mod and check it:

```sh
cp -r herdr-app/mods/htask ~/.config/herdr-app/mods/
herdr-app check ~/.config/herdr-app/mods/htask
```

Then add it to your layout. Shipped layouts are read-only, so do this in your own copy
(`herdr-app do layout.clone '{"name":"main","as":"my-layout"}'`), in
`~/.config/herdr-app/layouts/<layout>.json`:

1. **The panel.** Add `{ "id": "htask", "type": "block", "content": { "mod": "htask" } }` where
   you want it, for example as a child of a right-hand stack (`"type": "stack"`) next to Files
   and Changes.
2. **The status-bar chip** (needed for blocked-task toasts and the badge). Add it to your status
   row: `{ "id": "status-htask", "type": "block", "content": { "mod": "htask", "props": { "view": "chip" } }, "size": { "weight": 1.3 }, "min": 96 }`.
   It shows done/total for the focused repo and how many tasks are blocked. Click it to show or
   hide the panel. It assumes a column with id `panel` holding a stack `panel-body`; change
   `togglePanel()` in `common.js` if your layout differs.
3. **A tab-bar button** (optional). If your tab bar mod draws panel buttons, add one that runs
   `layout.select {stack: "panel-body", child: "htask"}` and `layout.show {id: "panel"}`. The chip
   publishes `shared("htask.summary")` = `{project, done, total, blocked}` for a `2/5` badge and
   a dot while anything is blocked.

In the panel:

- click a task to see its description, its agent and when it last changed, plus buttons for
  Start, Done, Unblock, Drop or Reopen;
- click a task's status dot to mark it done, or to reopen it;
- type in the box at the bottom and press Enter to add a task for the next agent;
- in-progress and blocked tasks show their agent's live state (`t6 working`). Click it to jump to
  that terminal. If the agent has exited or its terminal has closed, the task says so;
- **Done** shows the five most recent tasks; **Archive** puts away this repo's done tasks.

Spaces on SSH machines run htask on that machine, against that machine's own database. Install
it there once (`scp htask <machine>:~/.local/bin/htask`). Remote spaces refresh every 5 seconds.

## Herdr terminal UI

```sh
herdr plugin link "$PWD"
```

Bind a key in `~/.config/herdr/config.toml`, then run `herdr server reload-config`:

```toml
[[keys.command]]
key = "prefix+t"
type = "plugin_action"
command = "calvin.htask.open"
description = "open task panel"
```

Panel keys: `j`/`k` scroll, `d` show or hide done tasks, `v` show or hide descriptions, `q` close.

For progress in the sidebar, add the `$tasks` token (done/total for the agent's repo, updated
whenever an agent in that pane changes a task):

```toml
[ui.sidebar.agents]
rows = [["state_icon", "machine", "workspace", "tab"], ["agent", "$tasks"]]

[ui.sidebar.spaces]
rows = [["state_icon", "workspace", "$tasks"], ["branch", "git_status"]]
```

## Claude Code hooks

Add both to `~/.claude/settings.json` (replace `<repo>` with where you cloned this):

```json
"hooks": {
  "PostToolUse": [
    { "matcher": "TaskCreate|TaskUpdate|TodoWrite",
      "hooks": [ { "type": "command", "command": "~/.local/bin/htask hook claude", "timeout": 10 } ] },
    { "matcher": "*",
      "hooks": [ { "type": "command", "command": "<repo>/hooks/claude-inbox.sh", "timeout": 10 } ] }
  ],
  "UserPromptSubmit": [
    { "hooks": [ { "type": "command", "command": "<repo>/hooks/claude-inbox.sh", "timeout": 10 } ] }
  ]
}
```

- **`htask hook claude`** copies Claude's own task tool (`TaskCreate`/`TaskUpdate`, or the older
  `TodoWrite`) into htask, so Claude sessions fill the panel without being told to.
- **`claude-inbox.sh`** tells Claude about tasks you changed in the panel, at its next tool call
  or prompt, including Claude's own task id so it updates its list instead of undoing your change.
  It runs on every tool call; a shell check (about 3 ms) skips Python unless htask has written
  since that session last looked.

Both always exit 0, so a broken hook can never block a tool call.

## Agent instructions

**Claude Code** (`~/.claude/CLAUDE.md`, with the hooks above):

```markdown
## Task tracking (htask)

The Herdr task panel shows your plan. A hook copies your own task tool (TaskCreate/TaskUpdate,
or TodoWrite) into it, so for any task with more than one step, plan with that tool as usual:
subject = short title, description = what done looks like, and keep statuses current.

Use the `htask` CLI only for what the task tool can't say (ids come from `htask list`):
- `htask list` at the start, to pick up open tasks earlier sessions left in this repo.
- `htask note <id> "<progress, findings, next step>"` to leave information for the human.
- `htask block <id> -m "<what you need>"` when you are waiting on the user or something
  external. This notifies the human.
- Don't `htask add` steps you already created with the task tool: they would appear twice.
```

**Codex, Pi and other agents** (`~/.codex/AGENTS.md`, `~/.pi/agent/AGENTS.md`, or a project's
`AGENTS.md`):

```markdown
## Task tracking (htask)

For any task with more than one step, record the plan with `htask` so it shows in
the Herdr task panel. Tasks are scoped to the current git repo.

- `htask list` to see open tasks first, so you pick up existing work instead of duplicating it.
- `htask add "<short title>" -d "<what done looks like>"` for each step.
- `htask start <id>` before working on a step, `htask done <id>` after verifying it.
- `htask note <id> "<progress, findings, next step>"` to leave information for the human.
- `htask block <id> -m "<what you need>"` when you are waiting on the user or something external. This notifies the human.
- A message starting with `[Herdr task panel]` means the human changed one of your tasks: follow it and update your plan.
```

If you change tasks from a terminal yourself, add `--by you` (`htask --by you done 4`) so agents
hear about it.

## CLI reference

```sh
htask add "title" [-d "description"] [--status todo|doing|blocked|done|dropped]
htask start|done|drop|reopen <id>...      # reopen = back to to-do (also unblocks)
htask block <id> -m "what you need"
htask note <id> "text"
htask edit <id> [--title ...] [-d ...]
htask list [--all] [--archived] [--json]
htask clean [--days 7] [--everywhere] [--dry-run]   # archive old done/dropped tasks
htask summary                             # JSON: counts here + blocked tasks everywhere
htask panel                               # the terminal panel (curses)
```

Global options: `--project <dir>` (default: the git root of the current directory) and
`--by <who>`. `HTASK_DB` overrides the database path.

## Data

- `tasks`: one row per task. `project` is the repo root; `agent` and `pane_id` (Herdr app
  terminal like `t6`, or TUI pane like `w1:p2`) are filled in automatically; `external_id` ties a
  row to a Claude task; `archived_at` is set by `htask clean`.
- `changes`: who changed what (`by = 'you'` for the human), read by the Claude inbox hook.
- `hook_cursor`: how far each Claude session has read `changes`.

Query it directly, for example:
`sqlite3 ~/.local/share/herdr-tasks/tasks.db 'select status, count(*) from tasks group by 1'`.

## Tests

```sh
python3 -m unittest discover tests
```

## License

MIT

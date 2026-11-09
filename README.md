# htask: a task panel for coding agents in Herdr

A side panel for [Herdr](https://herdr.dev) that shows what your coding agents have finished,
what they're working on, what's blocked, and what's left. Agents record tasks with a small
`htask` CLI in one shared SQLite database. The panel follows the terminal you focus, shows that
repo's tasks, and updates as soon as any agent writes.

<p align="center">
  <img src="preview.png" width="420" alt="The Tasks panel in the Herdr desktop app: To do, Done, Dropped and Archived filter chips, a blocked task with its reason, a task in progress, three to-do tasks, the five most recent done tasks with Show 5 more, and four archived ones, with a Tasks 10/15 button and a red dot in the tab bar">
</p>

The panel showing this repo's own tasks. The status bar gets a chip with the same count and how
many tasks are blocked across all repos: <img src="docs/chip.png" height="22" alt="Status-bar chip: 10/15, 5 blocked">

(The middle of the panel, which was empty, is cut out of the screenshot.)

It works with both Herdr front ends:

- **Herdr desktop app** (`herdr-app`): a native panel mod, a status-bar chip, a toast when a
  task becomes blocked, and a done/total badge on the panel's button.
- **Herdr terminal UI** (`herdr`): a plugin pane, plus a `$tasks` progress token for the sidebar.

## How it works

- **Agents write tasks** with `htask add`, `start`, `done`, `note` and `block`, or, for Claude Code
  and Codex, a hook copies the agent's own task list or plan automatically. Tasks belong to the git repo the command
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

## Install

```sh
git clone https://github.com/calvinp0/herdr-htask
cd herdr-htask
./install.sh
htask connect all        # or the panel's Agents button
```

`install.sh` links `htask` and `htask-claude-inbox` into `~/.local/bin`, copies the desktop-app
mod into `~/.config/herdr-app/mods/htask` (if you have the app), links the terminal-UI plugin
(if you have `herdr`), and finishes with `htask doctor`.

`htask connect all` sets up every agent it finds: for Claude Code, the hooks in
`~/.claude/settings.json` and the instructions in `~/.claude/CLAUDE.md`; for Codex, the `update_plan`
hook in `~/.codex/hooks.json` and the instructions in `~/.codex/AGENTS.md`; for Pi, the instructions
in `~/.pi/agent/AGENTS.md`. It backs up each file before changing it, never rewrites a file
that's already right, and `htask connect <agent> --remove` takes out exactly what it added.
`htask connect status` shows where each agent stands. Agents started afterwards pick it up.
Then set up the panel below.

### Moving or updating

Nothing outside the checkout names the checkout: agents run `htask`, and the Claude hooks run
`~/.local/bin/htask` and `~/.local/bin/htask-claude-inbox`. So:

- **After moving or renaming the folder**, run `./install.sh` from its new place. It re-points
  the links and the plugin.
- **After `git pull`**, run `./install.sh` too: the desktop-app mod is a copy, so it only changes
  when it's copied again.
- **`htask doctor`** checks the links, the Claude hooks, the plugin link and whether the app mod
  matches the checkout, and says what to run when something is off. If htask can't run, the
  status chip shows a red `htask ✗`.

## Herdr desktop app

`install.sh` copies the mod into `~/.config/herdr-app/mods/htask` and checks it. Or ask the agent
running in Herdr: *"Read ~/.config/herdr-app/AGENTS.md, then add this mod:
https://github.com/calvinp0/herdr-htask"*. It follows [RECIPE.md](RECIPE.md).

Then add it to your layout. Shipped layouts are read-only, so do this in your own copy
(`herdr-app do layout.clone '{"name":"main","as":"my-layout"}'`), in
`~/.config/herdr-app/layouts/<layout>.json`:

1. **The status-bar chip** (needed for blocked-task toasts and the badge). Add it to your status
   row: `{ "id": "status-htask", "type": "block", "content": { "mod": "htask", "props": { "view": "chip" } }, "size": { "weight": 1.3 }, "min": 96 }`.
   It shows done/total for the focused repo and how many tasks are blocked. Click it to show or
   hide the panel.
2. **The panel** (optional). Add `{ "id": "htask", "type": "block", "content": { "mod": "htask" } }`
   where you want it, for example as a child of a right-hand stack next to Files and Changes. The
   chip finds it wherever it is: it selects it in its stack and shows what was hiding it. Without a
   panel block, the chip opens the panel as a floating window instead.
3. **A tab-bar button** (optional). If your tab bar mod draws panel buttons, add one that selects
   the htask block in its stack and shows the stack's column. The chip publishes
   `shared("htask.summary")` = `{project, done, total, blocked}` for a `2/5` badge and a dot while
   anything is blocked.

In the panel:

- click a task to see its description, its agent and when it last changed, plus buttons for
  Mark in progress, Block, Done, Unblock, Drop or Reopen. These only change the task's status
  (blocking from the panel has no reason; agents and `htask block <id> -m "..."` can give one);
- on a to-do, **▸ Run…** starts an agent on it. Every choice says where it goes: **New Claude
  tab**, **New Codex tab**, ... (the agents installed for that space) opens a new tab in the repo
  with the task as the agent's first message; **Send to t6 (Pi, idle)** types it into an agent
  already running in the repo. Nothing goes to an agent you didn't pick. The message asks the
  agent to run `htask start <id>`, which claims the task for its terminal, so the task moves to
  In progress with that agent's live state (`t15 working`) and to Done when it finishes;
- click a task's status dot to mark it done, or to reopen it;
- type in the box at the bottom and press Enter to add a task for the next agent;
- in-progress and blocked tasks show their agent's live state (`t6 working`). Click it to jump to
  that terminal. If the agent has exited or its terminal has closed, the task says so;
- the **To do**, **Done**, **Dropped** and **Archived** chips show or hide those sections (Blocked
  and In progress always show; Dropped and Archived start hidden); the panel remembers them. Done
  shows the five most recent tasks, with **Show N more** / **Show fewer** under them;
- **Archive** in the header puts away all of this repo's done tasks; a done or dropped task's own
  **Archive** button puts away just that one. Reopen an archived task to bring it back.

The chips can be keys too: bind `htask.toggle-todo`, `htask.toggle-done`, `htask.toggle-dropped`
or `htask.toggle-archived` in `~/.config/herdr-app/keys.json`, for example
`"global": { "ctrl-alt-t": "htask.toggle-todo" }`.

Spaces on SSH machines run htask on that machine, against that machine's own database. Install
it there once (`scp htask <machine>:~/.local/bin/htask`). Remote spaces refresh every 5 seconds.

## Herdr terminal UI

`install.sh` links the plugin (`herdr plugin link`). Bind a key in `~/.config/herdr/config.toml`, then run `herdr server reload-config`:

```toml
[[keys.command]]
key = "prefix+t"
type = "plugin_action"
command = "calvin.htask.open"
description = "open task panel"
```

Panel keys: `j`/`k` scroll, `t` show or hide to-do tasks, `d` done, `x` dropped, `a` archived,
`v` descriptions, `q` close.

For progress in the sidebar, add the `$tasks` token (done/total for the agent's repo, updated
whenever an agent in that pane changes a task):

```toml
[ui.sidebar.agents]
rows = [["state_icon", "machine", "workspace", "tab"], ["agent", "$tasks"]]

[ui.sidebar.spaces]
rows = [["state_icon", "workspace", "$tasks"], ["branch", "git_status"]]
```

## Claude Code hooks

`htask connect claude` adds these. To do it by hand, add both to `~/.claude/settings.json`. They
go through the links `install.sh` makes, so they keep working if you move the checkout:

```json
"hooks": {
  "PostToolUse": [
    { "matcher": "TaskCreate|TaskUpdate|TodoWrite",
      "hooks": [ { "type": "command", "command": "~/.local/bin/htask hook claude", "timeout": 10 } ] },
    { "matcher": "*",
      "hooks": [ { "type": "command", "command": "~/.local/bin/htask-claude-inbox", "timeout": 10 } ] }
  ],
  "UserPromptSubmit": [
    { "hooks": [ { "type": "command", "command": "~/.local/bin/htask-claude-inbox", "timeout": 10 } ] }
  ]
}
```

- **`htask hook claude`** copies Claude's own task tool (`TaskCreate`/`TaskUpdate`, or the older
  `TodoWrite`) into htask, so Claude sessions fill the panel without being told to.
- **`htask-claude-inbox`** (`hooks/claude-inbox.sh`) tells Claude about tasks you changed in the panel, at its next tool call
  or prompt, including Claude's own task id so it updates its list instead of undoing your change.
  It runs on every tool call; a shell check (about 3 ms) skips Python unless htask has written
  since that session last looked.

Both always exit 0, so a broken hook can never block a tool call.

## Codex hook

`htask connect codex` adds this to `~/.codex/hooks.json` (Codex needs `[features] hooks = true` in
its `config.toml`, and asks you to approve a new hook the next time it starts):

```json
"hooks": {
  "PostToolUse": [
    { "matcher": "^update_plan$",
      "hooks": [ { "type": "command", "command": "~/.local/bin/htask hook codex", "timeout": 10 } ] }
  ]
}
```

Each `update_plan` resends the whole plan, so htask mirrors it by step text: new steps are added,
statuses follow, and a step a revised plan leaves out is dropped (unless it was done). Codex may run
hooks from its background app-server rather than the agent's terminal; then htask asks herdr-core
for the live Codex terminal working in that repo, and leaves the terminal empty if there are several.
When you change a Codex task in the panel, the message typed to Codex asks it to update its plan to
match, so its next `update_plan` doesn't undo your change.

Not every Codex has `update_plan`: in its code mode (only an `exec` tool that calls others), the plan
tool isn't offered, so the hook never fires and Codex follows the instructions' fallback, `htask add` /
`start` / `done`. Its commands also run without `HC_TERMINAL_ID`; htask then finds the Codex terminal
through herdr-core, as the hook does.

In Codex's `workspace-write` sandbox, htask's writes (to `~/.local/share/herdr-tasks`) need approval.
To stop the prompts, choose "always allow" for `htask` when Codex asks (it saves
`prefix_rule(pattern=["htask"], decision="allow")` in `~/.codex/rules/default.rules`), or add the
folder to `[sandbox_workspace_write] writable_roots` in `~/.codex/config.toml`. htask doesn't change
Codex's permissions for you.

## Agent instructions

`htask connect` adds these, between `<!-- htask:start -->` and `<!-- htask:end -->` markers. By hand:

**Claude Code** (`~/.claude/CLAUDE.md`, with the hooks above). Not every Claude Code session has
a task-list tool, so the instructions cover both cases:

```markdown
## Task tracking (htask)

The Herdr task panel shows your plan. For any task with more than one step, record the plan in
one of two ways, depending on your tools:

- **If you have a task-list tool** (TaskCreate/TaskUpdate, or TodoWrite): plan with it as usual
  (subject = short title, description = what done looks like) and keep statuses current. A hook
  copies it into the panel. Don't also `htask add` those steps.
- **If you don't have one:** use the `htask` CLI itself: `htask add "<short title>" -d "<what done
  looks like>"` for each step, `htask start <id>` before working on one, `htask done <id>` after
  verifying it.

Either way, use the `htask` CLI for (ids come from `htask list`):
- `htask list` at the start, to pick up open tasks earlier sessions left in this repo.
- `htask note <id> "<progress, findings, next step>"` to leave information for the human.
- `htask block <id> -m "<what you need>"` when you are waiting on the user or something
  external. This notifies the human.
```

If a session does both, the hook doesn't add a duplicate: a task from Claude's tool is linked to
an unlinked `htask add` task with the same title, from the same terminal, in the same repo.

**Codex** (`~/.codex/AGENTS.md`, with the hook above):

```markdown
## Task tracking (htask)

The Herdr task panel shows your plan. For any task with more than one step:

- **Plan with your `update_plan` tool** as usual (short step names) and keep the statuses current.
  A hook copies the plan into the panel. Don't also `htask add` those steps.
- **If `update_plan` isn't available:** use the `htask` CLI itself: `htask add "<short title>" -d
  "<what done looks like>"` for each step, `htask start <id>` before working on one, `htask done
  <id>` after verifying it.

Either way, use the `htask` CLI for (ids come from `htask list`):
- `htask list` at the start, to pick up open tasks earlier sessions left in this repo.
- `htask note <id> "<progress, findings, next step>"` to leave information for the human.
- `htask block <id> -m "<what you need>"` when you are waiting on the user or something external. This notifies the human.
- A message starting with `[Herdr task panel]` means the human changed one of your tasks: follow it, and update your plan to match so your next update doesn't undo it.
```

**Pi and other agents** (`~/.pi/agent/AGENTS.md`, or a project's `AGENTS.md`):

```markdown
## Task tracking (htask)

For any task with more than one step, record the plan with `htask` so it shows in
the Herdr task panel. Tasks are scoped to the current git repo.

- `htask list` to see open tasks first, so you pick up existing work instead of duplicating it.
- `htask add "<short title>" -d "<what done looks like>"` for each step.
- `htask start <id>` before working on a step, `htask done <id>` after verifying it.
- `htask note <id> "<progress, findings, next step>"` to leave information for the human.
- `htask block <id> -m "<what you need>"` when you are waiting on the user or something external. This notifies the human.
- Keep using your own todo tool as well; htask is the record the human reads.
- A message starting with `[Herdr task panel]` means the human changed one of your tasks: follow it and update your plan.
```

If you change tasks from a terminal yourself, add `--by you` (`htask --by you done 4`) so agents
hear about it.

## CLI reference

```sh
htask add "title" [-d "description"] [--status todo|doing|blocked|done|dropped]
htask start|done|drop|reopen <id>...      # reopen = back to to-do (also unblocks); start claims the task for this terminal
htask block <id> -m "what you need"
htask note <id> "text"
htask edit <id> [--title ...] [-d ...]
htask list [--all] [--archived] [--json]
htask archive <id>...                     # archive done/dropped tasks now
htask clean [--days 7] [--everywhere] [--dry-run]   # archive old done/dropped tasks
htask summary                             # JSON: counts here + blocked tasks everywhere
htask panel                               # the terminal panel (curses)
htask doctor                              # check the install
htask connect status|all|claude|codex|pi [--remove]   # set agents up (or take htask out)
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

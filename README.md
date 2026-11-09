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

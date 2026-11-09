# Agents: hooks and instructions

`htask connect all` sets all of this up (see the [README](../README.md)). This page shows what it
adds, for doing it by hand or checking it.

## Claude Code

Two hooks in `~/.claude/settings.json`. They run through the links `install.sh` makes, so they keep
working if you move the checkout.

```json
"hooks": {
  "PostToolUse": [
    { "matcher": "TaskCreate|TaskUpdate|TodoWrite|ExitPlanMode",
      "hooks": [ { "type": "command", "command": "~/.local/bin/htask hook claude", "timeout": 10 } ] },
    { "matcher": "*",
      "hooks": [ { "type": "command", "command": "~/.local/bin/htask-claude-inbox", "timeout": 10 } ] }
  ],
  "UserPromptSubmit": [
    { "hooks": [ { "type": "command", "command": "~/.local/bin/htask-claude-inbox", "timeout": 10 } ] }
  ]
}
```

**`htask hook claude`** copies Claude's own task list into htask:

- `TaskCreate` / `TaskUpdate` (or the older `TodoWrite`) become tasks.
- Dependencies Claude sends (`addBlockedBy`) become htask dependencies.
- An approved plan (`ExitPlanMode`) becomes one "Plan: …" task with the plan's opening and file path.

**`htask-claude-inbox`** tells Claude about tasks you changed in the panel, at its next tool call or
prompt. It includes Claude's own task id, so Claude updates its list instead of undoing your change.
A quick shell check (about 3 ms) skips the rest unless htask has written since Claude last looked.

Both hooks always exit 0, so a broken hook can't block a tool call.

## Codex

One hook in `~/.codex/hooks.json`. Codex needs `[features] hooks = true` in its `config.toml`, and
asks you to approve a new hook the next time it starts.

```json
"hooks": {
  "PostToolUse": [
    { "matcher": "^update_plan$",
      "hooks": [ { "type": "command", "command": "~/.local/bin/htask hook codex", "timeout": 10 } ] }
  ]
}
```

- Each `update_plan` resends the whole plan, so steps are matched by text. A step a revised plan
  leaves out is dropped, unless it was done.
- Codex can run hooks and commands without `HC_TERMINAL_ID`. htask then asks herdr-core for the Codex
  terminal working in that repo, and records none if there are several.
- When you change a Codex task in the panel, the message to Codex asks it to update its plan too.
- **Code mode:** some Codex setups have no `update_plan` (only an `exec` tool). Then the hook never
  fires, and Codex uses the `htask` commands from its instructions instead.

**Sandbox prompts.** In Codex's `workspace-write` sandbox, htask's writes need approval. To stop the
prompts, choose "always allow" for `htask` when Codex asks, or add `~/.local/share/herdr-tasks` to
`[sandbox_workspace_write] writable_roots` in `~/.codex/config.toml`. htask doesn't change Codex's
permissions for you.

## Instructions

`htask connect` adds these between `<!-- htask:start -->` and `<!-- htask:end -->` markers.

**Claude Code** (`~/.claude/CLAUDE.md`). Not every session has a task-list tool, so it covers both:

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

After a plan is approved in plan mode, record its steps the same way, in order.

Either way, use the `htask` CLI for (ids come from `htask list`):
- `htask list` at the start, to pick up open tasks earlier sessions left in this repo
  (`htask next` names the first one that isn't waiting on another).
- `htask depend <id> --on <earlier id>` when a step can't start before another is done
  (or `htask add ... --after <id>`).
- `htask add "<title>" --from <id>` for follow-up work a task turns up, so it shows where it came from.
- `htask note <id> "<progress, findings, next step>"` to leave information for the human.
- `htask block <id> -m "<what you need>"` when you are waiting on the user or something
  external. This notifies the human.
```

If a session does both, there's no duplicate: a task from Claude's tool is linked to an unlinked
`htask add` task with the same title, terminal and repo.

**Codex** (`~/.codex/AGENTS.md`):

```markdown
## Task tracking (htask)

The Herdr task panel shows your plan. For any task with more than one step:

- **Plan with your `update_plan` tool** as usual (short step names) and keep the statuses current.
  A hook copies the plan into the panel. Don't also `htask add` those steps.
- **If `update_plan` isn't available:** use the `htask` CLI itself: `htask add "<short title>" -d
  "<what done looks like>"` for each step, `htask start <id>` before working on one, `htask done
  <id>` after verifying it.

Either way, use the `htask` CLI for (ids come from `htask list`):
- `htask list` at the start, to pick up open tasks earlier sessions left in this repo
  (`htask next` names the first one that isn't waiting on another).
- `htask depend <id> --on <earlier id>` when a step can't start before another is done
  (or `htask add ... --after <id>`).
- `htask add "<title>" --from <id>` for follow-up work a task turns up, so it shows where it came from.
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
- `htask add "<short title>" -d "<what done looks like>"` for each step, in order; add
  `--after <id>` when a step can't start before an earlier one is done. `htask next` names the
  first step that isn't waiting.
- `htask start <id>` before working on a step, `htask done <id>` after verifying it.
- `htask add "<title>" --from <id>` for follow-up work a task turns up, so it shows where it came from.
- `htask note <id> "<progress, findings, next step>"` to leave information for the human.
- `htask block <id> -m "<what you need>"` when you are waiting on the user or something external. This notifies the human.
- Keep using your own todo tool as well; htask is the record the human reads.
- A message starting with `[Herdr task panel]` means the human changed one of your tasks: follow it and update your plan.
```

If you change tasks from a terminal yourself, add `--by you` (`htask --by you done 4`) so agents
hear about it.

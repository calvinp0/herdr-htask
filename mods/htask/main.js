// htask: what the agents have done and what's left, for the repo of the focused terminal.
// Two views: the panel (default; the right-hand stack) and props.view "chip" (status bar, chip.js).
// Both read htask (one SQLite DB for every agent) and redraw when it writes or focus changes repo.
import { View, div, svg } from "gpui-kit";
import { v_flex, h_flex, Scrollbar, InputState, Input } from "gpui-base";
import { theme, props, run, agents, terminals, hc, notify, nextCommand, closeOverlay } from "herdr";
import { htask, htaskError, qualify, location, watchSignal } from "./common.js";
import { Chip } from "./chip.js";

// Theme colour for each task status: the same colours the agents list uses.
const COLOR = { doing: "working", blocked: "blocked", todo: "muted", done: "done", dropped: "dim" };

// How many done tasks the Done section shows; the rest are a "+N more" line (Archive clears them).
const DONE_SHOWN = 5;

// The panel's sections in display order, as [title, rows, hidden count, can collapse]. Empty ones
// are skipped. Blocked comes first because it needs you. Within each open section, the focused
// terminal's tasks come first, then the rest of the repo's in id order (sort is stable). Done shows
// the newest few until show.allDone; Dropped shows only with its chip on.
export function sections(tasks, terminal, show, machine) {
  const mine = (task) => Boolean(terminal) && qualify(machine, task.pane_id) === terminal;
  const by = (status) => tasks.filter((task) => task.status === status)
    .sort((a, b) => Number(mine(b)) - Number(mine(a)));
  const out = [["Blocked", by("blocked"), 0], ["In progress", by("doing"), 0]];
  if (show.todo) out.push(["To do", by("todo"), 0]);
  if (show.done) {
    const done = tasks.filter((task) => task.status === "done")
      .sort((a, b) => (b.completed_at ?? 0) - (a.completed_at ?? 0));
    const rows = show.allDone ? done : done.slice(0, DONE_SHOWN);
    out.push(["Done", rows, done.length - rows.length, done.length > DONE_SHOWN]);
  }
  if (show.dropped) {
    out.push(["Dropped", tasks.filter((task) => task.status === "dropped")
      .sort((a, b) => (b.updated_at ?? 0) - (a.updated_at ?? 0)), 0]);
  }
  return out;
}

// The agent that made a task, live: { addr, state } where state is its agent status
// (working, blocked, done, idle), "running" (an agent that doesn't report one), "exited" (the
// terminal is a plain shell again) or "gone" (the terminal closed). null when the task wasn't
// made in a Herdr app terminal (by hand, or in the TUI).
const SHELLS = new Set(["bash", "zsh", "fish", "sh", "dash", "ksh", "nu", "pwsh", "powershell"]);
function owner(task, machine) {
  if (!/^t\d+$/.test(task.pane_id ?? "")) return null;
  const addr = qualify(machine, task.pane_id);
  const term = terminals().find((x) => x.address === addr);
  if (!term || term.state !== "live") return { addr, state: "gone" };
  const agent = agents().find((a) => a.address === addr);
  if (agent) return { addr, state: agent.status };
  return { addr, state: term.agent && !SHELLS.has(term.agent) ? "running" : "exited" };
}
const OWNER_COLOR = { working: "working", blocked: "blocked", running: "working", done: "dim", idle: "dim", exited: "blocked", gone: "blocked" };
const OWNER_WORD = { exited: "agent exited", gone: "terminal closed" };

// The buttons an expanded task offers, by status: [label, htask command].
const ACTIONS = {
  todo: [["Start", "start"], ["Block", "block"], ["Done", "done"], ["Drop", "drop"]],
  doing: [["Done", "done"], ["Block", "block"], ["Back to to-do", "reopen"], ["Drop", "drop"]],
  blocked: [["Unblock", "reopen"], ["Done", "done"], ["Drop", "drop"]],
  done: [["Reopen", "reopen"], ["Archive", "archive"]],
  dropped: [["Reopen", "reopen"], ["Archive", "archive"]],
};

// What the owning agent is told when you change its task from the panel.
const TELL = {
  done: (ref) => `${ref} is marked done. Treat it as finished and don't change its status back.`,
  drop: (ref) => `${ref} is dropped. Stop working on it.`,
  reopen: (ref, task) => (task.status === "blocked" ? `${ref} is unblocked. You can carry on with it.` : `${ref} is back in to-do.`),
  start: (ref) => `${ref} is marked in progress.`,
  block: (ref) => `${ref} is marked blocked. Hold off on it until the human unblocks it.`,
};

function ago(seconds) {
  const s = Math.max(0, Date.now() / 1000 - seconds);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

// The filter chips under the progress bar, in order. Blocked and In progress always show.
const FILTERS = [["todo", "To do"], ["done", "Done"], ["dropped", "Dropped"], ["archived", "Archived"]];
const DEFAULT_SHOW = { todo: true, done: true, dropped: false, archived: false, allDone: false };

function loadShow() {
  try { return { ...DEFAULT_SHOW, ...JSON.parse(localStorage.getItem("show") ?? "{}") }; }
  catch { return { ...DEFAULT_SHOW }; }
}

class Panel {
  init(_props, cx) {
    this.tasks = []; this.project = null; this.cwd = null; this.terminal = null;
    this.open = new Set(); this.width = 0;
    // Which sections show; remembered per panel copy. Archived tasks are only fetched while shown.
    this.show = loadShow(); this.archived = [];
    // Key commands for this mod, e.g. keys.json "mod:htask" or "global": "htask.toggle-done".
    cx.spawn(async (cx) => {
      for (;;) {
        const c = await nextCommand();
        const name = /^toggle-(todo|done|dropped|archived)$/.exec(c)?.[1];
        if (name) this.flip(name, cx);
      }
    });
    this.input = InputState.new({ placeholder: "Add a task, then Enter" });
    this.input.on("submit", (_e, cx) => this.add(cx));
    this.input.on("focus", (_e, cx) => { this.typing = true; cx.notify(); });
    this.input.on("blur", (_e, cx) => { this.typing = false; cx.notify(); });
    watchSignal(cx, (cx) => { if (!this.machine) this.refresh(cx); });
    // A remote space can't be watched: poll it every 5 s. Here, every 15 s is only a backstop
    // for writes that bypass htask (sqlite3 by hand) or a watch that failed.
    this.ticks = 0;
    cx.timer.every(5000, (cx) => { if (this.machine || ++this.ticks % 3 === 0) this.refresh(cx); });
  }

  refresh(cx) {
    const cwd = this.cwd, machine = this.machine;
    if (!cwd) return;
    if (this.loading) { this.again = true; return; }
    this.loading = true;
    cx.spawn(async (cx) => {
      try {
        const r = await htask(machine, ["--project", cwd, "list", "--all", "--json"]);
        if (cwd !== this.cwd || machine !== this.machine) return;
        if (r.code !== 0) throw new Error(htaskError(machine, r));
        const data = JSON.parse(r.stdout);
        let archived = [];
        if (this.show.archived) {
          const a = await htask(machine, ["--project", cwd, "list", "--archived", "--json"]);
          if (a.code !== 0) throw new Error(htaskError(machine, a));
          archived = JSON.parse(a.stdout).tasks.sort((x, y) => (y.archived_at ?? 0) - (x.archived_at ?? 0));
        }
        if (cwd !== this.cwd || machine !== this.machine) return;
        this.project = data.project; this.tasks = data.tasks; this.archived = archived; this.error = null;
      } catch (e) {
        if (cwd === this.cwd && machine === this.machine) { this.error = String(e?.message ?? e); this.tasks = []; this.project = null; }
      } finally {
        this.loading = false;
        if (this.again) { this.again = false; this.refresh(cx); }
        cx.notify();
      }
    });
  }

  // Run an htask command on this project, as you (--by you: Claude's inbox hook passes your
  // changes on). The signal watch reloads the list afterwards. `then` runs once it succeeded.
  htask(args, cx, then) {
    const project = this.project, machine = this.machine;
    if (!project) return;
    this.note = null;
    cx.spawn(async (cx) => {
      try {
        const r = await htask(machine, ["--project", project, "--by", "you", ...args]);
        if (r.code !== 0) throw new Error(htaskError(machine, r));
        then?.(cx);
        if (machine) this.refresh(cx);  // no watch on a remote space
      } catch (e) {
        this.note = String(e?.message ?? e);
      }
      cx.notify();
    });
  }

  // Change a task's status, then tell the agent working on it, if one still is.
  change(task, cmd, cx) {
    const own = owner(task, this.machine);
    this.htask([cmd, String(task.id)], cx, (cx) => this.tell(task, cmd, own, cx));
  }

  // Claude sessions hear about it from the inbox hook on their next step, without a new turn.
  // Other agents get a message typed into their terminal. hc send refuses while the agent waits
  // on a question (typing could answer it): then the toast sends you there instead.
  tell(task, cmd, own, cx) {
    if (!own || own.state === "gone" || own.state === "exited" || !TELL[cmd]) return;
    const ref = `htask #${task.id} "${task.title}"`, what = TELL[cmd](ref, task);
    const there = { name: "agent.focus", args: { terminal: own.addr } };
    if (task.agent === "claude") {
      notify({ title: `Claude in ${own.addr} will see this at its next step`, body: what, level: "info", action: there });
      return;
    }
    cx.spawn(async () => {
      const text = `[Herdr task panel] The human changed your task: ${what} Keep htask in sync with this.`;
      const r = await hc(["send", own.addr, text]).catch((e) => ({ code: 1, stderr: String(e?.message ?? e) }));
      if (r.code === 0) notify({ title: `Told ${own.addr}`, body: what, level: "info", action: there });
      else notify({
        title: `Couldn't tell ${own.addr}`, level: "warning", action: there,
        body: own.state === "blocked" ? "It's waiting on a question. Tell it there." : (r.stderr || r.stdout || "").trim(),
      });
    });
  }

  add(cx) {
    const title = this.input.value().trim();
    if (!title) return;
    this.input.set_value("");
    this.htask(["add", "--agent", "you", "--", title], cx);
  }

  flip(name, cx) {
    this.show = { ...this.show, [name]: !this.show[name] };
    try { localStorage.setItem("show", JSON.stringify(this.show)); } catch { /* not remembered */ }
    if (name === "archived") { this.archived = []; this.refresh(cx); }
    cx.notify();
  }

  toggle(id, cx) {
    if (this.open.has(id)) this.open.delete(id); else this.open.add(id);
    cx.notify();
  }

  dot(task, t) {
    const color = t[COLOR[task.status]] ?? t.dim;
    const mark = task.status === "doing"
      ? svg("mods/workspace-chrome/spinner.svg").size(12).text_color(color).spin(900)
      : task.status === "todo"
        ? div().size(9).rounded(5).border_1().border_color(color)
        : task.status === "done"
          ? svg("mods/htask/check.svg").size(12).text_color(color)
          : div().size(9).rounded(5).bg(color);
    const next = task.status === "done" || task.status === "dropped" ? "reopen" : "done";
    return h_flex().id(`dot-${task.id}`).w(14).h(19).flex_none().items_center().justify_center().rounded(4)
      .hover((s) => s.bg(t.raised)).tooltip(next === "done" ? "Mark done" : "Reopen")
      .on_click((_e, cx) => { cx.stop_propagation(); this.change(task, next, cx); })
      .child(mark);
  }

  ownerTag(task, own, t) {
    const color = t[OWNER_COLOR[own.state]] ?? t.dim, live = own.state !== "gone";
    return div().id(`owner-${task.id}`).h(19).px(4).flex().flex_none().items_center().gap(4).rounded(4)
      .text_size(10).text_color(color)
      .when(live, (e) => e.cursor_pointer().hover((s) => s.bg(t.raised)).tooltip(`Show ${own.addr}`)
        .on_click((_e, cx) => { cx.stop_propagation(); run("agent.focus", { terminal: own.addr }); }))
      .child(`${own.addr} ${OWNER_WORD[own.state] ?? own.state}`);
  }

  actions(task, t) {
    return h_flex().pl(22).pt(4).gap(5).children((ACTIONS[task.status] ?? []).map(([label, cmd]) =>
      div().id(`act-${task.id}-${cmd}`).px(7).py(2).rounded(5).text_size(11).cursor_pointer()
        .bg(t.raised).text_color(t.foreground).hover((s) => s.bg(t.hover))
        .on_click((_e, cx) => { cx.stop_propagation(); this.change(task, cmd, cx); })
        .child(label)));
  }

  row(task, t) {
    const open = this.open.has(task.id), done = task.status === "done";
    const mine = this.terminal && qualify(this.machine, task.pane_id) === this.terminal;
    // "this terminal" only tells tasks apart when the open ones come from more than one
    // terminal, and never on finished rows.
    const label = mine && this.mixed && task.status !== "done" && task.status !== "dropped";
    const active = task.status === "doing" || task.status === "blocked";
    const own = active ? owner(task, this.machine) : null;
    const orphaned = own && (own.state === "exited" || own.state === "gone");
    const detail = (text, color) => div().pl(22).text_size(11.5).text_color(color).child(text);
    return v_flex().id(`task-${task.id}`).flex_none().px(8).py(5).gap(2).rounded(7).cursor_pointer()
      .when(open, (e) => e.bg(t.selected)).hover((s) => s.bg(t.hover))
      .on_click((_e, cx) => this.toggle(task.id, cx))
      .child(h_flex().gap(8).items_start()
        .child(this.dot(task, t))
        .child(div().flex_1().min_w(0).text_color(done || task.status === "dropped" ? t.muted : t.foreground).when(!open, (e) => e.truncate()).child(task.title))
        .when(label, (e) => e.child(div().h(19).flex().items_center().text_size(10).text_color(t.accent).child("this terminal")))
        .when(Boolean(own) && !mine, (e) => e.child(this.ownerTag(task, own, t)))
        .child(div().h(19).flex().items_center().text_size(10.5).text_color(t.dim).child(`#${task.id}`)))
      .when(Boolean(task.note) && !done, (e) => e.child(detail(`↳ ${task.note}`, task.status === "blocked" ? t.blocked : t.muted)))
      .when(orphaned, (e) => e.child(detail("Nobody is working on this now. Pick it up or move it back to to-do.", t.blocked)))
      .when(open && Boolean(task.description), (e) => e.child(detail(task.description, t.muted)))
      .when(open, (e) => e.child(detail(
        [task.agent, task.pane_id, `updated ${ago(task.updated_at)}`].filter(Boolean).join(" · "), t.dim)))
      .when(open, (e) => e.child(this.actions(task, t)));
  }

  render(cx) {
    const loc = location();
    if (loc.cwd && (loc.cwd !== this.cwd || loc.machine !== this.machine)) {
      this.cwd = loc.cwd; this.machine = loc.machine; this.open.clear(); this.refresh(cx);
    }
    if (loc.cwd) this.terminal = loc.terminal;

    const t = theme();
    const counted = this.tasks.filter((task) => task.status !== "dropped");
    const done = counted.filter((task) => task.status === "done").length;
    const barWidth = Math.max(0, this.width - 28);
    const name = this.project ? this.project.split("/").pop() : "";
    const owners = new Set(this.tasks.filter((task) => task.status !== "done" && task.status !== "dropped" && task.pane_id)
      .map((task) => task.pane_id));
    this.mixed = owners.size > 1;
    const shown = sections(this.tasks, this.terminal, this.show, this.machine).filter(([, rows]) => rows.length);
    if (this.show.archived && this.archived.length) shown.push(["Archived", this.archived, 0]);

    const empty = this.error ? this.error
      : !this.cwd ? "Focus a terminal to see its repo's tasks."
      : this.loading && !this.project ? "Loading tasks…"
      : `No tasks in ${name} yet. Add one below, or agents add them with:`;

    return v_flex().id("htask").size_full().min_h(0).rounded(10).overflow_hidden().bg(t.background)
      .border_1().border_color(t.border).text_color(t.foreground).text_size(13)
      .on_size_change((size, cx) => { if (size.width !== this.width) { this.width = size.width; cx.notify(); } })
      .child(h_flex().h(42).flex_none().px(14).gap(8).items_center()
        .child(div().font_semibold().child("Tasks"))
        .when(Boolean(name), (e) => e.child(div().min_w(0).px(5).py(1).rounded(4).border_1().border_color(t.border).text_size(10).text_color(t.muted).truncate().child(name)))
        .child(div().flex_1())
        .child(div().text_size(11).text_color(t.muted).child(`${done}/${counted.length}`))
        .when(done > 0, (e) => e.child(div().id("htask-archive").px(6).py(2).rounded(5).text_size(11).cursor_pointer()
          .text_color(t.muted).hover((s) => s.bg(t.hover)).tooltip("Archive this repo's done tasks (htask clean --days 0)")
          .on_click((_e, cx) => this.htask(["clean", "--days", "0"], cx)).child("Archive")))
        // Opened as a window (a layout with no panel block): a close button. Stopping the press
        // keeps it from dragging the window instead.
        .when(Boolean(props()?.overlay), (e) => e.child(div().id("htask-close").size(22).flex().items_center()
          .justify_center().rounded(5).cursor_pointer().text_color(t.muted).hover((s) => s.bg(t.hover))
          .on_mouse_down("left", (_e, cx) => cx.stop_propagation())
          .on_click((_e, cx) => { cx.stop_propagation(); closeOverlay(props().overlay); }).child("×")))
        )
      .child(div().mx(14).h(3).flex_none().rounded(2).bg(t.border)
        .child(div().h_full().rounded(2).bg(t.done).w(counted.length ? barWidth * done / counted.length : 0)))
      .child(h_flex().flex_none().px(14).pt(10).gap(6).items_center()
        .children(FILTERS.map(([name, label]) => {
          const on = this.show[name];
          return div().id(`show-${name}`).px(9).py(2).rounded(10).text_size(11).cursor_pointer().border_1()
            .border_color(on ? t.border : t.background).bg(on ? t.raised : t.background)
            .text_color(on ? t.foreground : t.dim).hover((st) => st.bg(t.hover))
            .tooltip(`${on ? "Hide" : "Show"} ${label.toLowerCase()} tasks`)
            .on_click((_e, cx) => this.flip(name, cx)).child(label);
        })))
      .child(div().flex_1().min_h(0).relative().mt(8)
        .child(v_flex().id("htask-list").absolute().inset_0().overflow_y_scroll().px(6).pb(8)
          .children(shown.map(([title, rows, more, collapsible]) => v_flex().flex_none()
            .child(div().px(8).pt(8).pb(3).text_size(10.5).font_semibold().text_color(t.dim).child(`${title.toUpperCase()}  ${rows.length + more}`))
            .children(rows.map((task) => this.row(task, t)))
            // Done's "Show N more" / "Show fewer" (remembered with the chips).
            .when(Boolean(collapsible), (e) => e.child(div().id(`more-${title}`).ml(30).mr(8).my(2).px(4).py(2).rounded(5)
              .text_size(11).text_color(t.accent).cursor_pointer().hover((st) => st.bg(t.hover))
              .on_click((_e, cx) => this.flip("allDone", cx))
              .child(more > 0 ? `Show ${more} more` : "Show fewer")))))
          .when(this.show.archived && !this.archived.length && Boolean(this.project) && !this.loading, (e) => e.child(
            div().px(8).pt(8).text_size(11).text_color(t.dim).child(`Nothing archived in ${name}.`)))
          .when(!shown.length, (e) => e.child(v_flex().p(8).gap(6).text_color(t.dim)
            .child(empty)
            .when(!this.error && Boolean(this.project), (e) => e.child(
              div().px(8).py(5).rounded(6).bg(t.raised).text_size(11.5).text_color(t.muted).child('htask add "title" -d "what done looks like"'))))))
        .child(Scrollbar.vertical("htask-list").absolute().inset_0()))
      .when(Boolean(this.note), (e) => e.child(div().px(14).pb(6).text_size(11).text_color(t.blocked).child(this.note)))
      .when(Boolean(this.project), (e) => e.child(h_flex().flex_none().p(10).gap(8).border_t(1).border_color(t.border)
        .child(div().id("htask-add").flex_1().min_w(0).h(32).px(10).flex().items_center().rounded(8).border_1()
          .border_color(this.typing ? t.accent : t.border).cursor_text().on_mouse_down("left", (_e, cx) => cx.stop_propagation())
          .child(Input.new(this.input).h_full().text_size(12).text_color(t.foreground)))
        .child(div().id("htask-add-button").h(32).px(12).flex().items_center().rounded(8).text_size(12).cursor_pointer()
          .bg(t.raised).text_color(t.foreground).hover((s) => s.bg(t.hover))
          .on_click((_e, cx) => this.add(cx)).child("Add"))));
  }
}

export default class Tasks extends View {
  init(p, cx) {
    this.view = props()?.view === "chip" ? new Chip() : new Panel();
    this.view.init(p, cx);
  }

  render(cx) {
    return this.view.render(cx);
  }
}

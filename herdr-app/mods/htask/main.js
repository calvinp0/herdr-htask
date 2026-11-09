// htask: what the agents have done and what's left, for the repo of the focused terminal.
// Two views: the panel (default; the right-hand stack) and props.view "chip" (status bar, chip.js).
// Both read htask (one SQLite DB for every agent) and redraw when it writes or focus changes repo.
import { View, div, svg } from "gpui-kit";
import { v_flex, h_flex, Scrollbar } from "gpui-base";
import { exec, theme, props } from "herdr";
import { HTASK, location, watchSignal } from "./common.js";
import { Chip } from "./chip.js";

// Theme colour for each task status: the same colours the agents list uses.
const COLOR = { doing: "working", blocked: "blocked", todo: "muted", done: "done", dropped: "dim" };

// Groups the tasks into the panel's sections, in display order. Empty sections are skipped.
//
// TODO(calvin): this is the policy for what you see first. Things to decide:
//   - should "Blocked" sit above "In progress", since it needs you?
//   - should tasks from the focused terminal (task.pane_id === terminal) come first in each section?
//   - how many done tasks to keep: all, the last N, only today's? (task.completed_at: unix seconds)
//   - do "dropped" tasks appear at all?
export function sections(tasks, terminal, showDone) {
  const by = (status) => tasks.filter((task) => task.status === status);
  const out = [["In progress", by("doing")], ["Blocked", by("blocked")], ["To do", by("todo")]];
  if (showDone) out.push(["Done", by("done")]);
  return out;
}

function ago(seconds) {
  const s = Math.max(0, Date.now() / 1000 - seconds);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

class Panel {
  init(_props, cx) {
    this.tasks = []; this.project = null; this.cwd = null; this.terminal = null;
    this.open = new Set(); this.showDone = true; this.width = 0;
    watchSignal(cx, (cx) => this.refresh(cx));
    // Backstop for writes that bypass htask (sqlite3 by hand) or a watch that failed.
    cx.timer.every(15000, (cx) => this.refresh(cx));
  }

  refresh(cx) {
    const cwd = this.cwd;
    if (!cwd || this.remote) return;
    if (this.loading) { this.again = true; return; }
    this.loading = true;
    cx.spawn(async (cx) => {
      try {
        const r = await exec(HTASK(), ["--project", cwd, "list", "--all", "--json"], { timeout: 10000 });
        if (cwd !== this.cwd) return;
        if (r.code !== 0) throw new Error((r.stderr || r.stdout).trim());
        const data = JSON.parse(r.stdout);
        this.project = data.project; this.tasks = data.tasks; this.error = null;
      } catch (e) {
        if (cwd === this.cwd) this.error = String(e?.message ?? e);
      } finally {
        this.loading = false;
        if (this.again) { this.again = false; this.refresh(cx); }
        cx.notify();
      }
    });
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
    return h_flex().w(14).h(19).flex_none().items_center().justify_center().child(mark);
  }

  row(task, t) {
    const open = this.open.has(task.id), done = task.status === "done";
    const mine = this.terminal && task.pane_id === this.terminal;
    const detail = (text, color) => div().pl(22).text_size(11.5).text_color(color).child(text);
    return v_flex().id(`task-${task.id}`).flex_none().px(8).py(5).gap(2).rounded(7).cursor_pointer()
      .when(open, (e) => e.bg(t.selected)).hover((s) => s.bg(t.hover))
      .on_click((_e, cx) => this.toggle(task.id, cx))
      .child(h_flex().gap(8).items_start()
        .child(this.dot(task, t))
        .child(div().flex_1().min_w(0).text_color(done ? t.muted : t.foreground).when(!open, (e) => e.truncate()).child(task.title))
        .when(mine, (e) => e.child(div().h(19).flex().items_center().text_size(10).text_color(t.accent).child("this terminal")))
        .child(div().h(19).flex().items_center().text_size(10.5).text_color(t.dim).child(`#${task.id}`)))
      .when(Boolean(task.note) && !done, (e) => e.child(detail(`↳ ${task.note}`, task.status === "blocked" ? t.blocked : t.muted)))
      .when(open && Boolean(task.description), (e) => e.child(detail(task.description, t.muted)))
      .when(open, (e) => e.child(detail(
        [task.agent, task.pane_id, `updated ${ago(task.updated_at)}`].filter(Boolean).join(" · "), t.dim)));
  }

  render(cx) {
    const loc = location();
    if (loc.remote !== this.remote) { this.remote = loc.remote; }
    if (loc.cwd && loc.cwd !== this.cwd) { this.cwd = loc.cwd; this.open.clear(); this.refresh(cx); }
    if (loc.cwd) this.terminal = loc.terminal;

    const t = theme();
    const counted = this.tasks.filter((task) => task.status !== "dropped");
    const done = counted.filter((task) => task.status === "done").length;
    const barWidth = Math.max(0, this.width - 28);
    const name = this.project ? this.project.split("/").pop() : "";
    const shown = sections(this.tasks, this.terminal, this.showDone).filter(([, rows]) => rows.length);

    const empty = this.remote ? "Tasks live on this computer, so remote spaces have none yet."
      : this.error ? this.error
      : !this.cwd ? "Focus a terminal to see its repo's tasks."
      : this.loading && !this.project ? "Loading tasks…"
      : `No tasks in ${name} yet. Agents add them with:`;

    return v_flex().id("htask").size_full().min_h(0).rounded(10).overflow_hidden().bg(t.background)
      .border_1().border_color(t.border).text_color(t.foreground).text_size(13)
      .on_size_change((size, cx) => { if (size.width !== this.width) { this.width = size.width; cx.notify(); } })
      .child(h_flex().h(42).flex_none().px(14).gap(8).items_center()
        .child(div().font_semibold().child("Tasks"))
        .when(Boolean(name), (e) => e.child(div().min_w(0).px(5).py(1).rounded(4).border_1().border_color(t.border).text_size(10).text_color(t.muted).truncate().child(name)))
        .child(div().flex_1())
        .child(div().text_size(11).text_color(t.muted).child(`${done}/${counted.length}`))
        .child(div().id("htask-done").px(6).py(2).rounded(5).text_size(11).cursor_pointer()
          .text_color(this.showDone ? t.foreground : t.dim).bg(this.showDone ? t.raised : t.background).hover((s) => s.bg(t.hover))
          .on_click((_e, cx) => { this.showDone = !this.showDone; cx.notify(); })
          .tooltip(this.showDone ? "Hide done tasks" : "Show done tasks").child("Done")))
      .child(div().mx(14).h(3).flex_none().rounded(2).bg(t.border)
        .child(div().h_full().rounded(2).bg(t.done).w(counted.length ? barWidth * done / counted.length : 0)))
      .child(div().flex_1().min_h(0).relative().mt(8)
        .child(v_flex().id("htask-list").absolute().inset_0().overflow_y_scroll().px(6).pb(8)
          .children(shown.map(([title, rows]) => v_flex().flex_none()
            .child(div().px(8).pt(8).pb(3).text_size(10.5).font_semibold().text_color(t.dim).child(`${title.toUpperCase()}  ${rows.length}`))
            .children(rows.map((task) => this.row(task, t)))))
          .when(!shown.length, (e) => e.child(v_flex().p(8).gap(6).text_color(t.dim)
            .child(empty)
            .when(!this.remote && !this.error && Boolean(this.project), (e) => e.child(
              div().px(8).py(5).rounded(6).bg(t.raised).text_size(11.5).text_color(t.muted).child('htask add "title" -d "what done looks like"'))))))
        .child(Scrollbar.vertical("htask-list").absolute().inset_0()));
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

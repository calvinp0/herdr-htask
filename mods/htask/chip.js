// The status-bar chip: "✓ 2/5" for the focused terminal's repo and how many tasks are blocked
// anywhere. Click: show or hide the Tasks panel. It is the copy that is always alive, so it also
// raises a toast when a task becomes blocked and publishes the counts for the tab bar's button.
import { div, svg } from "gpui-kit";
import { h_flex } from "gpui-base";
import { notify, shared, setShared, theme } from "herdr";
import { htask, htaskError, qualify, SUMMARY_KEY, location, togglePanel, panelShown, watchSignal, NOT_HERE } from "./common.js";

// Blocked task ids already announced, one list per machine (ids are per machine's DB).
// Persisted, so a restart doesn't repeat them; an id leaves its list once the task is unblocked,
// so blocking it again announces it again. Blocked tasks on a machine are seen while one of its
// spaces is focused (this computer's are watched all the time).
const notifiedKey = (machine) => (machine ? `htask.notified.${machine}` : "htask.notified");
const name = (path) => (path ?? "").split("/").pop();
// A Herdr app terminal address (t7): the toast can jump there.
const isTerminal = (id) => /^t\d+$/.test(id ?? "");

export class Chip {
  init(_props, cx) {
    this.summary = null; this.cwd = null;
    // This computer's blocked tasks are announced even while a remote space is focused.
    watchSignal(cx, (cx) => (this.machine ? this.checkHere(cx) : this.refresh(cx)));
    // A remote space can't be watched: poll it every 5 s; here every 15 s is only a backstop.
    this.ticks = 0;
    cx.timer.every(5000, (cx) => { if (this.machine || ++this.ticks % 3 === 0) this.refresh(cx); });
    this.refresh(cx);
  }

  refresh(cx) {
    if (this.loading) { this.again = true; return; }
    this.loading = true;
    const cwd = this.cwd, machine = this.machine;
    cx.spawn(async (cx) => {
      try {
        const r = await htask(machine, cwd ? ["--project", cwd, "summary"] : ["summary"]);
        if (r.code !== 0) throw new Error(htaskError(machine, r));
        const data = JSON.parse(r.stdout);
        if (cwd === this.cwd && machine === this.machine) { this.summary = data; this.error = null; this.publish(data); }
        this.announce(machine, data.blocked);
      } catch (e) {
        this.error = String(e?.message ?? e);
      } finally {
        this.loading = false;
        if (this.again) { this.again = false; this.refresh(cx); }
        cx.notify();
      }
    });
  }

  checkHere(cx) {
    cx.spawn(async () => {
      try {
        const r = await htask(null, ["summary"]);
        if (r.code === 0) this.announce(null, JSON.parse(r.stdout).blocked);
      } catch { /* the next refresh reports errors */ }
    });
  }

  publish(data) {
    const c = data.counts, total = c.todo + c.doing + c.blocked + c.done;
    const next = { project: data.project, done: c.done, total, blocked: data.blocked.length };
    // setShared re-renders every mod: only when something changed.
    if (JSON.stringify(shared(SUMMARY_KEY)) !== JSON.stringify(next)) setShared(SUMMARY_KEY, next);
  }

  announce(machine, blocked) {
    const key = notifiedKey(machine), seen = new Set(shared(key) ?? []);
    for (const task of blocked) {
      if (seen.has(task.id)) continue;
      notify({
        title: `Blocked: ${task.title}`,
        body: [`${machine ? `${machine}: ` : ""}${name(task.project)} #${task.id}`, task.note].filter(Boolean).join(" · "),
        level: "warning",
        ...(isTerminal(task.pane_id) ? { action: { name: "agent.focus", args: { terminal: qualify(machine, task.pane_id) } } } : {}),
      });
    }
    const now = blocked.map((task) => task.id);
    if (now.length !== seen.size || now.some((id) => !seen.has(id))) setShared(key, now);
  }

  render(cx) {
    const loc = location();
    if (loc.cwd && (loc.cwd !== this.cwd || loc.machine !== this.machine)) {
      this.cwd = loc.cwd; this.machine = loc.machine; this.refresh(cx);
    }

    const t = theme(), s = shared(SUMMARY_KEY), on = panelShown();
    const blocked = this.summary?.blocked ?? [];
    const tip = this.error === NOT_HERE ? NOT_HERE
      : this.error ? `htask: ${this.error}\nRun htask doctor (or ./install.sh in the htask folder).`
      : blocked.length ? `Blocked:\n${blocked.map((b) => `${name(b.project)} #${b.id} ${b.title}`).join("\n")}`
      : s?.total ? `${s.done} of ${s.total} tasks done in ${name(s.project)}` : "No tasks in this repo";
    return h_flex().id("htask-chip").size_full().px(8).gap(6).items_center().cursor_pointer().text_size(11.5)
      .text_color(on ? t.foreground : t.muted).hover((st) => st.bg(t.hover))
      .on_mouse_down("left", (_e, cx) => cx.stop_propagation())
      .on_click(() => togglePanel()).tooltip(tip)
      .child(svg("mods/htask/htask.svg").size(13).flex_none())
      // A broken install (htask moved, missing on a remote machine) shows here, not just in the tooltip.
      .child(this.error === NOT_HERE
        ? div().flex_none().text_color(t.dim).child("Tasks")
        : this.error
        ? div().flex_none().text_color(t.blocked).child("htask ✗")
        : div().flex_none().child(s?.total ? `${s.done}/${s.total}` : "Tasks"))
      .when(blocked.length > 0, (el) => el.child(h_flex().flex_none().gap(4).items_center().text_color(t.blocked)
        .child(div().size(6).rounded(3).bg(t.blocked)).child(`${blocked.length} blocked`)));
  }
}

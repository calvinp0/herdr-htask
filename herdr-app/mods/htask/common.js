// Shared by the panel (main.js) and the status chip (chip.js).
import { spaces, panes, focused, home, layout, run, exec, watchFolder } from "herdr";

export const HTASK = () => `${home()}/.local/bin/htask`;
// htask rewrites signal/changed after every write. Watch that, never the DB folder: SQLite
// creates and deletes -wal/-shm there on every connection, our own reads included.
export const SIGNAL_DIR = () => `${home()}/.local/share/herdr-tasks/signal`;
// What the chip publishes for the tab bar's Tasks button: {project, done, total, blocked}.
export const SUMMARY_KEY = "htask.summary";

// The focused terminal's folder. A mod pane (this panel, Files, ...) has none: callers keep the last.
export function location() {
  const f = focused(), space = spaces().find((s) => s.active);
  const pane = f?.pane ? panes().find((p) => p.pane === f.pane) : null;
  return { cwd: pane?.cwd || f?.cwd || null, terminal: f?.terminal ?? null, remote: Boolean(space?.machine) };
}

export function find(node, id) {
  if (node?.id === id) return node;
  for (const child of node?.children ?? []) {
    const found = find(child, id);
    if (found) return found;
  }
  return null;
}

// Is the Tasks panel showing? (The fleet layout's right column "panel", stack "panel-body".)
export function panelShown() {
  const root = layout(), panel = find(root, "panel"), body = find(root, "panel-body");
  return Boolean(panel && !panel.hidden && body?.active === "htask");
}

export function togglePanel() {
  if (panelShown()) run("layout.hide", { id: "panel" });
  else { run("layout.select", { stack: "panel-body", child: "htask" }); run("layout.show", { id: "panel" }); }
}

// Re-run `load` whenever htask writes, for as long as this copy lives.
export function watchSignal(cx, load) {
  cx.spawn(async (cx) => {
    try {
      for (;;) {
        await watchFolder(SIGNAL_DIR());
        load(cx);
      }
    } catch {
      // No signal folder yet (htask has never written): make it, then watch again.
      const made = await exec("mkdir", ["-p", SIGNAL_DIR()]).catch(() => null);
      if (made?.code === 0) watchSignal(cx, load);
    }
  });
}

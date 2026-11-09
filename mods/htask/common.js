// Shared by the panel (main.js) and the status chip (chip.js).
import { spaces, panes, focused, home, layout, run, exec, watchFolder, openOverlay } from "herdr";

export const HTASK = () => `${home()}/.local/bin/htask`;

// Run htask for a space: here, or on its SSH machine through herdr-core. The remote copy is
// looked for in that machine's ~/.local/bin, then on its PATH; each machine has its own DB.
export function htask(machine, args) {
  if (!machine) return exec(HTASK(), args, { timeout: 10000 });
  const script = 'h="$HOME/.local/bin/htask"; [ -x "$h" ] || h=htask; exec "$h" "$@"';
  return exec("sh", ["-lc", script, "htask", ...args], { on: machine, timeout: 15000 });
}

// The error to show when htask failed: say so plainly when it isn't installed there.
export function htaskError(machine, r) {
  const text = (r.stderr || r.stdout || "").trim();
  if (machine && (r.code === 127 || /not found/.test(text)))
    return `htask isn't installed on ${machine}. Copy it to ~/.local/bin/htask there.`;
  return text || `htask exited with ${r.code}`;
}

// Task ids are per machine, and so are terminal addresses: qualify both for a remote space.
export const qualify = (machine, addr) => (machine && addr ? `${machine}/${addr}` : addr);
// htask rewrites signal/changed after every write. Watch that, never the DB folder: SQLite
// creates and deletes -wal/-shm there on every connection, our own reads included.
export const SIGNAL_DIR = () => `${home()}/.local/share/herdr-tasks/signal`;
// What the chip publishes for the tab bar's Tasks button: {project, done, total, blocked}.
export const SUMMARY_KEY = "htask.summary";

// The focused terminal's folder. A mod pane (this panel, Files, ...) has none: callers keep the last.
export function location() {
  const f = focused(), space = spaces().find((s) => s.active);
  const pane = f?.pane ? panes().find((p) => p.pane === f.pane) : null;
  return { cwd: pane?.cwd || f?.cwd || null, terminal: f?.terminal ?? null, machine: space?.machine ?? null };
}

export function find(node, id) {
  if (node?.id === id) return node;
  for (const child of node?.children ?? []) {
    const found = find(child, id);
    if (found) return found;
  }
  return null;
}

// Where the panel is in the shown layout, with no assumptions about ids: the htask block that is
// the panel (not the chip), its stack if it is one of a stack's children, and the nodes above it.
// null when the layout has no panel block.
function panelSpot() {
  const path = [];
  const walk = (node) => {
    if (!node) return false;
    path.push(node);
    if (node.type === "block" && node.content?.mod === "htask" && !node.content?.props?.view) return true;
    for (const child of node.children ?? []) if (walk(child)) return true;
    path.pop();
    return false;
  };
  if (!walk(layout())) return null;
  const block = path[path.length - 1], parent = path[path.length - 2];
  const stack = parent?.type === "stack" ? parent : null;
  // What to hide: climb from the stack (or the block) while the parent holds nothing else, so the
  // whole side column goes, not just its contents. Never the root.
  let i = path.length - (stack ? 2 : 1);
  while (i > 1 && (path[i - 1].children ?? []).length === 1) i -= 1;
  return { block, stack, above: path.slice(1, -1), container: path[i] };
}

// Is the Tasks panel showing?
export function panelShown() {
  const spot = panelSpot();
  if (!spot || spot.block.hidden || spot.above.some((node) => node.hidden)) return false;
  return !spot.stack || spot.stack.active === spot.block.id;
}

// Show or hide the panel. A layout without a panel block gets it as a floating window instead,
// with a close button (one window: opening it again replaces it).
export function togglePanel() {
  const spot = panelSpot();
  if (!spot) {
    openOverlay({ mod: "htask", kind: "window", key: "htask", width: 380, height: 640 });
    return;
  }
  if (panelShown()) {
    run("layout.hide", { id: spot.container.id });
    return;
  }
  if (spot.stack) run("layout.select", { stack: spot.stack.id, child: spot.block.id });
  for (const node of [...spot.above, spot.block]) if (node.hidden && node.id) run("layout.show", { id: node.id });
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

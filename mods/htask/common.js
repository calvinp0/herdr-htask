// Shared by the panel (main.js) and the status chip (chip.js).
import { spaces, panes, focused, home, layout, run, exec, watchFolder, openOverlay, window } from "herdr";
import { spotIn } from "./layout-edit.js";

export const HTASK = () => `${home()}/.local/bin/htask`;
// This mod's version: the same as the htask CLI's (a test keeps them in step). The panel compares
// it with `htask --version` on each machine it uses, and says which side to update.
export const MOD_VERSION = "0.2.3";

const parts = (v) => (v ?? "").split(".").map((n) => parseInt(n, 10) || 0);
export function compareVersions(a, b) {
  const [x, y] = [parts(a), parts(b)];
  for (let i = 0; i < 3; i++) if ((x[i] ?? 0) !== (y[i] ?? 0)) return (x[i] ?? 0) < (y[i] ?? 0) ? -1 : 1;
  return 0;
}

// Run htask for a space: here, or on its SSH machine through herdr-core. The remote copy is
// looked for in that machine's ~/.local/bin, then on its PATH; each machine has its own DB.
// The htask CLI runs on Linux and macOS. The app on Windows uses it on the machines it connects to
// over SSH; for the PC's own spaces there's nothing to run, and that isn't an error worth red.
export const NOT_HERE = "htask isn't on this computer (Windows). Spaces on a machine that has it work.";
export const notHere = (machine) => !machine && window()?.platform === "windows";

export function htask(machine, args, timeout) {
  if (notHere(machine)) return Promise.resolve({ code: 127, stdout: "", stderr: NOT_HERE });
  if (!machine) return exec(HTASK(), args, { timeout: timeout ?? 10000 });
  const script = 'h="$HOME/.local/bin/htask"; [ -x "$h" ] || h=htask; exec "$h" "$@"';
  return exec("sh", ["-lc", script, "htask", ...args], { on: machine, timeout: timeout ?? 15000 });
}

// The error to show when htask failed: say so plainly when it isn't installed there.
export function htaskError(machine, r) {
  const text = (r.stderr || r.stdout || "").trim();
  if (text === NOT_HERE) return text;
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

// Where the panel is in the shown layout (layout-edit.js; no assumptions about ids).
function panelSpot() {
  return spotIn(layout());
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

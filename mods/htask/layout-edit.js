// Adding htask to a layout tree, as a pure function: no Herdr imports, so it can be tested on its own
// (tests/layout_edit.test.mjs) against real layouts. main.js applies the result with layout.set.

// Blocks that mark the right-hand panel stack (Files, Changes) and the status bar.
const PANEL_MODS = new Set(["files", "changes", "files-plus", "changes-plus"]);
const STATUS_MODS = new Set(["workspace-status", "workspace-status-plus"]);

export const isPanelBlock = (n) => n?.type === "block" && n.content?.mod === "htask" && !n.content?.props?.view;
export const isChipBlock = (n) => n?.type === "block" && n.content?.mod === "htask" && n.content?.props?.view === "chip";

// Where the panel is in a tree: the htask block, its stack if it is one of a stack's children, the
// nodes above it, and the container to hide/show (climbing while the parent holds nothing else).
// null when the tree has no panel block.
export function spotIn(root) {
  const path = [];
  const walk = (node) => {
    if (!node) return false;
    path.push(node);
    if (isPanelBlock(node)) return true;
    for (const child of node.children ?? []) if (walk(child)) return true;
    path.pop();
    return false;
  };
  if (!walk(root)) return null;
  const block = path[path.length - 1], parent = path[path.length - 2];
  const stack = parent?.type === "stack" ? parent : null;
  let i = path.length - (stack ? 2 : 1);
  while (i > 1 && (path[i - 1].children ?? []).length === 1) i -= 1;
  return { block, stack, above: path.slice(1, -1), container: path[i] };
}

// A copy of `root` with the Tasks panel and the status-bar chip added where they belong:
//   panel: into the stack that holds Files/Changes, else as a 360 px column at the right of a row root;
//   chip:  beside the status bar (before a Controls block if the bar is a row; a lone status block
//          is wrapped in a row of its height).
// Returns { tree, panel, chip }: whether each was added (false: already there, or no place for it).
export function addToLayout(root) {
  const tree = JSON.parse(JSON.stringify(root));
  const all = [];
  const walk = (node, parent) => { all.push([node, parent]); for (const c of node.children ?? []) walk(c, node); };
  walk(tree, null);
  const ids = new Set(all.map(([n]) => n.id).filter(Boolean));
  const fresh = (id) => { let x = id, i = 2; while (ids.has(x)) x = `${id}-${i++}`; ids.add(x); return x; };
  const has = (pred) => all.some(([n]) => pred(n));

  let panel = false, chip = false;
  if (!has(isPanelBlock)) {
    const stack = all.map(([n]) => n)
      .find((n) => n.type === "stack" && (n.children ?? []).some((c) => PANEL_MODS.has(c.content?.mod)));
    const block = { id: fresh("htask"), type: "block", content: { mod: "htask" } };
    if (stack) { stack.children.push(block); panel = true; }
    else if (tree.type === "row") { tree.children.push({ ...block, size: { px: 360 } }); panel = true; }
  }
  if (!has(isChipBlock)) {
    const entry = all.find(([n]) => n.type === "block" && STATUS_MODS.has(n.content?.mod));
    if (entry && entry[1]) {
      const [status, parent] = entry;
      const chipBlock = { id: fresh("status-htask"), type: "block", content: { mod: "htask", props: { view: "chip" } },
                          size: { weight: 1.3 }, min: 96 };
      if (parent.type === "row") {
        const i = parent.children.findIndex((c) => c.content?.mod === "controls");
        parent.children.splice(i < 0 ? parent.children.length : i, 0, chipBlock);
      } else {
        const row = { id: fresh("status-row"), type: "row", size: status.size, resizable: false,
                      children: [{ ...status, size: { weight: 6 } }, chipBlock] };
        parent.children[parent.children.indexOf(status)] = row;
      }
      chip = true;
    }
  }
  return { tree, panel, chip };
}

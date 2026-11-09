// node --test tests/layout_edit.test.mjs
// The mod's layout change (mods/htask/layout-edit.js) against layouts shaped like Herdr's own.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../mods/htask/layout-edit.js", import.meta.url), "utf8");
const { addToLayout, spotIn, isPanelBlock, isChipBlock } = await import("data:text/javascript," + encodeURIComponent(src));

// Herdr app 0.1.14's shipped "main" layout, trimmed to its structure.
const MAIN = {
  id: "root", type: "row", titlebar: "none", children: [
    { id: "sidebar", type: "column", size: { px: 268 }, children: [
      { id: "brand", type: "block", content: { mod: "workspace-chrome" } },
      { id: "spaces", type: "block", content: { mod: "spaces" } }] },
    { id: "work", type: "column", children: [
      { id: "tabs", type: "block", size: { px: 42 }, content: { mod: "tabs" } },
      { id: "work-body", type: "row", children: [
        { id: "main", type: "block", content: { tab: "active" } },
        { id: "panel", type: "column", hidden: true, size: { px: 368 }, children: [
          { id: "panel-body", type: "stack", children: [
            { id: "files", type: "block", content: { mod: "files" } },
            { id: "changes", type: "block", content: { mod: "changes" } }] }] }] },
      { id: "status", type: "block", size: { px: 28 }, content: { mod: "workspace-status" } }] }] };

const nodes = (tree) => { const out = []; const w = (n) => { out.push(n); (n.children ?? []).forEach(w); }; w(tree); return out; };

test("shipped main: panel joins Files/Changes, chip goes beside the status bar", () => {
  const { tree, panel, chip } = addToLayout(MAIN);
  assert.ok(panel && chip);
  const spot = spotIn(tree);
  assert.equal(spot.stack.id, "panel-body");
  assert.equal(spot.container.id, "panel");           // what the chip shows and hides
  const row = nodes(tree).find((n) => n.id === "status-row");
  assert.deepEqual(row.size, { px: 28 });
  assert.deepEqual(row.children.map((c) => c.content.mod), ["workspace-status", "htask"]);
  assert.ok(isChipBlock(row.children[1]));
  assert.equal(nodes(MAIN).length + 3, nodes(tree).length); // panel, row, chip; nothing else changed
  assert.ok(!nodes(MAIN).some(isPanelBlock));          // the original is untouched
});

test("adding twice changes nothing", () => {
  const once = addToLayout(MAIN).tree;
  const again = addToLayout(once);
  assert.ok(!again.panel && !again.chip);
  assert.deepEqual(again.tree, once);
});

test("a status row with Controls gets the chip just before it", () => {
  const fleetLike = JSON.parse(JSON.stringify(MAIN));
  const work = fleetLike.children[1];
  work.children[2] = { id: "status", type: "row", size: { px: 28 }, children: [
    { id: "status-main", type: "block", content: { mod: "workspace-status-plus" } },
    { id: "status-controls", type: "block", content: { mod: "controls" } }] };
  const { tree } = addToLayout(fleetLike);
  const status = nodes(tree).find((n) => n.id === "status");
  assert.deepEqual(status.children.map((c) => c.id), ["status-main", "status-htask", "status-controls"]);
});

test("ids never collide", () => {
  const taken = JSON.parse(JSON.stringify(MAIN));
  taken.children[1].children[0].id = "htask";          // something else already called htask
  const { tree } = addToLayout(taken);
  const ids = nodes(tree).map((n) => n.id);
  assert.equal(ids.length, new Set(ids).size);
  assert.equal(spotIn(tree).block.id, "htask-2");
});

test("no panel stack: a column at the right of the root", () => {
  const bare = { id: "root", type: "row", children: [{ id: "main", type: "block", content: { tab: "active" } }] };
  const { tree, panel, chip } = addToLayout(bare);
  assert.ok(panel && !chip);                           // no status bar to put a chip in
  assert.deepEqual(tree.children.at(-1).size, { px: 360 });
});

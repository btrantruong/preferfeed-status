import test from "node:test";
import assert from "node:assert/strict";
import { columns, layout, bands, fitScale, START, END } from "../flow.js";

const tr = [
  { step: 0, from: START, to: "A", n: 6 }, { step: 0, from: START, to: "B", n: 4 },
  { step: 1, from: "A", to: "B", n: 4 }, { step: 1, from: "A", to: END, n: 2 }, { step: 1, from: "B", to: END, n: 4 },
  { step: 2, from: "B", to: END, n: 4 }, // a participant whose log ended after two runs does not continue
];
const order = ["A", "B"];

test("columns order nodes and put END last", () => {
  const cols = columns(tr, 3, order);
  assert.deepEqual(cols[0], [{ node: "A", n: 6 }, { node: "B", n: 4 }]);
  assert.deepEqual(cols[1].map((c) => c.node), ["B", END]);
  assert.equal(cols[1].find((c) => c.node === END).n, 6);
});
test("node heights are proportional to participants", () => {
  const cols = columns(tr, 3, order), lay = layout(cols, 2, 5);
  assert.equal(lay.nodes["0|A"].h, 12); assert.equal(lay.nodes["0|B"].h, 8);
  assert.equal(lay.nodes["0|B"].y, 17);
});
test("bands conserve participants between columns", () => {
  const cols = columns(tr, 3, order), lay = layout(cols, 1, 0), bs = bands(tr, lay, 1);
  const into = (k, to) => bs.filter((b) => b.k === k && b.to === to).reduce((a, b) => a + b.n, 0);
  assert.equal(into(1, "B"), 4); assert.equal(into(1, END), 6);
  assert.equal(bs.filter((b) => b.k === 1).reduce((a, b) => a + b.h, 0), 10);
  const outOfA = bs.filter((b) => b.k === 1 && b.from === "A").reduce((a, b) => a + b.h, 0);
  assert.equal(outOfA, lay.nodes["0|A"].h);
});
test("fitScale fits the tallest column", () => {
  const cols = columns(tr, 3, order), s = fitScale(cols, 100, 10);
  const lay = layout(cols, s, 10);
  assert.ok(lay.height <= 100 + 1e-9);
  assert.equal(fitScale([[]], 100, 10), 0);
});

import test from "node:test";
import assert from "node:assert/strict";
import { linear, band, yTicks, thin } from "../svg.js";
import { clampPage } from "../pager.js";

test("linear maps and inverts", () => {
  const f = linear(0, 10, 100, 200);
  assert.equal(f(5), 150); assert.equal(f.invert(150), 5);
  assert.equal(linear(3, 3, 7, 9)(3), 7);
});
test("band gives equal slots with a gap", () => {
  const b = band(4, 0, 400, 0.2);
  assert.equal(b.step, 100); assert.equal(b.bw, 80); assert.equal(b(0), 10); assert.equal(b(3), 310);
});
test("yTicks uses 1, 2 or 5 times a power of ten and covers the maximum", () => {
  assert.deepEqual(yTicks(0, 4).ticks, [0, 1]);
  assert.deepEqual(yTicks(7, 4).ticks, [0, 2, 4, 6, 8]);
  const t = yTicks(83, 4); assert.ok(t.max >= 83 && t.ticks.length <= 5);
});
test("thin keeps labels apart", () => {
  assert.deepEqual(thin(10, 100, 50), [0, 5]);
  assert.deepEqual(thin(3, 300, 50), [0, 1, 2]);
});
test("clampPage", () => { assert.equal(clampPage(9, 3), 2); assert.equal(clampPage(-2, 3), 0); assert.equal(clampPage(1, 0), 0); });

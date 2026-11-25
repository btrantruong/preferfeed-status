import test from "node:test";
import assert from "node:assert/strict";
import { clamp, valueFromX, moveHandle, keyStep } from "../slider.js";

test("valueFromX rounds to the nearest step and clamps", () => {
  assert.equal(valueFromX(150, 100, 200, 20), 5);
  assert.equal(valueFromX(50, 100, 200, 20), 0);
  assert.equal(valueFromX(999, 100, 200, 20), 20);
  assert.equal(valueFromX(100, 100, 0, 20), 0);
});
test("handles keep at least minGap steps apart", () => {
  assert.deepEqual(moveHandle({ from: 2, to: 6 }, "from", 9, 20, 1), { from: 5, to: 6 });
  assert.deepEqual(moveHandle({ from: 2, to: 6 }, "to", 0, 20, 1), { from: 2, to: 3 });
  assert.deepEqual(moveHandle({ from: 2, to: 6 }, "to", 99, 20, 1), { from: 2, to: 20 });
  assert.deepEqual(moveHandle({ from: 2, to: 6 }, "from", -4, 20, 1), { from: 0, to: 6 });
});
test("keys: arrows one step, page keys an hour, home and end to the ends", () => {
  assert.equal(keyStep("ArrowRight", 5, 20, 4), 6);
  assert.equal(keyStep("ArrowLeft", 5, 20, 4), 4);
  assert.equal(keyStep("PageUp", 5, 20, 4), 9);
  assert.equal(keyStep("PageDown", 5, 20, 4), 1);
  assert.equal(keyStep("Home", 5, 20, 4), 0);
  assert.equal(keyStep("End", 5, 20, 4), 20);
  assert.equal(keyStep("a", 5, 20, 4), null);
});
test("clamp", () => { assert.equal(clamp(5, 0, 3), 3); assert.equal(clamp(-1, 0, 3), 0); });

import test from "node:test";
import assert from "node:assert/strict";
import { pickCondition } from "../charts/_cond.js";

test("pickCondition keeps a stored condition that has data", () => {
  assert.equal(pickCondition(["RANDOM", "ATTENTION"], "ATTENTION"), "ATTENTION");
});
test("pickCondition falls back to the first condition with data", () => {
  assert.equal(pickCondition(["ATTENTION", "PREFERENCE"], "RANDOM"), "ATTENTION");
  assert.equal(pickCondition(["PREFERENCE"], null), "PREFERENCE");
  assert.equal(pickCondition([], "RANDOM"), null);
});

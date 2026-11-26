import test from "node:test";
import assert from "node:assert/strict";
import { outcomeTree, retryStacks } from "../charts/_outcomes.js";

const rows = [
  { outcome: "done_first", last_error: "none", n: 5 }, { outcome: "done_retry", last_error: "none", n: 1 },
  { outcome: "in_session", last_error: "none", n: 2 }, { outcome: "left_no_error", last_error: "none", n: 3 },
  { outcome: "left_no_error_retried", last_error: "none", n: 1 }, { outcome: "left_error_no_retry", last_error: "reload", n: 2 },
  { outcome: "left_error_no_retry", last_error: "server", n: 1 }, { outcome: "left_retried_after_error", last_error: "idle", n: 4 },
];

test("outcomeTree: groups and levels add up to the total", () => {
  const t = outcomeTree(rows);
  assert.equal(t.total, 19);
  assert.deepEqual(t.groups, { done: 6, in_session: 2, left: 11 });
  const sum = (level) => t.table.filter((r) => r.level === level).reduce((a, r) => a + r.n, 0);
  assert.equal(sum(0), 19);
  assert.equal(sum(1), 19);
  assert.equal(sum(2), 11);
  assert.equal(sum(3), 7);
});
test("outcomeTree: error types follow their category, only when present", () => {
  const labels = outcomeTree(rows).table.map((r) => r.label);
  assert.deepEqual(labels.slice(labels.indexOf("error, no retry")),
    ["error, no retry", "last error: reload", "last error: server error", "retried after error", "last error: idle"]);
});
test("outcomeTree: empty input keeps the fixed rows", () => {
  const t = outcomeTree([]);
  assert.equal(t.total, 0);
  assert.equal(t.table.length, 10);
});
test("retryStacks counts per x value and outcome", () => {
  const r = [{ trigger: "idle", retries: 1, retry_outcome: "done", n: 2 }, { trigger: "none", retries: 2, retry_outcome: "left_no_final_error", n: 3 }];
  const s = retryStacks(r, "trigger", ["idle", "none"]);
  assert.deepEqual(s.map((x) => x.values), [[2, 0], [0, 0], [0, 0], [0, 3]]);
  assert.deepEqual(retryStacks(r, "retries", [1, 2])[0].values, [2, 0]);
});

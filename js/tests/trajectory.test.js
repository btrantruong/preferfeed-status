import test from "node:test";
import assert from "node:assert/strict";
import { xOf, profileColumns, batchList, maxBatch, warmEnd, signalsOf, available, rewardMean, centeredRange, niceTicks, segments } from "../trajectory/model.js";

const B = (n, m) => ({ batch: n, post_ids: [], mean_centered: m });
const attempt = { exchanges: [
  { endpoint: "init", signal_batch: null, batches: [B(1, [1, 0]), B(2, [-2, 0])], u_long: [0, 0] },
  { endpoint: "next_batch", signal_batch: 1, phase: "warmup", batches: [B(3, [0, 0])], u_long: [0, 0], u_short: null, rewards: null },
  { endpoint: "next_batch", signal_batch: 2, phase: "algorithm", batches: [B(4, [0, 0])], u_long: [0.5, -1], u_short: [3, -1], rewards: [1, -1] },
] };

test("a request sits at its signal batch or at the batch it served", () => {
  assert.deepEqual(profileColumns(attempt, "informed").map((q) => q.x), [1, 2]);
  assert.deepEqual(profileColumns(attempt, "informs").map((q) => q.x), [3, 4]);
  assert.equal(xOf(attempt.exchanges[0], "informs"), null);          // batches 1 and 2 were not chosen by a profile
});
test("batches, warm-up end and the signals of a batch", () => {
  assert.deepEqual(batchList(attempt).map((q) => q.batch), [1, 2, 3, 4]);
  assert.equal(maxBatch(attempt), 4);
  assert.equal(warmEnd(attempt), 3);
  assert.equal(signalsOf(attempt, 2), attempt.exchanges[2]);
  assert.equal(signalsOf(attempt, 4), null);
});
test("available reports what an older file lacks", () => {
  assert.deepEqual(available(attempt), { signalBatch: true, batchMeans: true, rewards: true, uShort: true });
  const old = { exchanges: [{ endpoint: "next_batch", batches: [{ batch: 3, post_ids: [] }], u_long: [0] }] };
  assert.deepEqual(available(old), { signalBatch: false, batchMeans: false, rewards: false, uShort: false });
  // an attempt with the init request only has the field, with no value
  assert.equal(available({ exchanges: [{ endpoint: "init", signal_batch: null, batches: [] }] }).signalBatch, true);
});
test("rewardMean ignores missing rewards", () => {
  assert.equal(rewardMean([1, null, 0]), 0.5);
  assert.equal(rewardMean([null]), null);
  assert.equal(rewardMean(null), null);
});
test("one range for the centered panels, with 0 inside", () => {
  const r = centeredRange(attempt);
  assert.ok(r.lo < -2 && r.hi > 3);
});
test("niceTicks and segments", () => {
  assert.deepEqual(niceTicks(-1.2, 1.2, 4), [-1, 0, 1]);
  assert.deepEqual(niceTicks(0, 0.4, 4), [0, 0.1, 0.2, 0.3, 0.4]);
  assert.deepEqual(segments([{ x: 1 }, { x: 2 }, { x: 4 }]).map((s) => s.length), [2, 1]);
});

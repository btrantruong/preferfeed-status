import test from "node:test";
import assert from "node:assert/strict";
import { durLabels, histMedian } from "../charts/_dur.js";

test("durLabels: one label per bin, matching the binning of cubes.dur_bin", () => {
  const L = durLabels([10, 60, 120]);
  assert.equal(L.short.length, 4);
  assert.deepEqual(L.short, ["<10s", "<1", "<2", ">2"]);
  assert.equal(L.range[0], "under 10 s"); assert.equal(L.range[1], "10 s to under 1 min"); assert.equal(L.range[3], "2 min or more");
});
test("histMedian interpolates inside a bin and handles empty and open bins", () => {
  const edges = [60, 120, 180];
  assert.equal(histMedian([0, 0, 0, 0], edges), null);
  assert.equal(histMedian([0, 4, 0, 0], edges), 1.5);               // all four in 1 to 2 minutes: the middle
  assert.equal(histMedian([2, 2, 0, 0], edges), 1);                 // half below one minute: at the edge
  assert.equal(histMedian([0, 0, 0, 3], edges), 3);                 // the open last bin gives its lower edge
});

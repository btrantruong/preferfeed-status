import test from "node:test";
import assert from "node:assert/strict";
import { dwellRadius, postOffset, drawSample, seedHash } from "../charts/_spot.js";

test("dwellRadius: area grows with dwell up to the cap; no dwell gives null", () => {
  assert.equal(dwellRadius(null, 30000, 1.5, 7), null);
  assert.equal(dwellRadius(30000, 30000, 1.5, 7), 7);
  assert.equal(dwellRadius(90000, 30000, 1.5, 7), 7);               // capped
  assert.equal(dwellRadius(0, 30000, 1.5, 7), 1.5);                 // never smaller than rMin
  const r1 = dwellRadius(7500, 30000, 0, 8), r2 = dwellRadius(30000, 30000, 0, 8);
  assert.ok(Math.abs(r2 * r2 / (r1 * r1) - 4) < 1e-9);              // 4 times the dwell, 4 times the area
});
test("postOffset spreads posts symmetrically in served order", () => {
  assert.deepEqual([0, 1, 2, 3, 4].map((k) => postOffset(k, 5, 0.3)), [-0.3, -0.15, 0, 0.15, 0.3]);
  assert.equal(postOffset(0, 1, 0.3), 0);
});

test("drawSample: seeded, without replacement, independent of the input order", () => {
  const users = Array.from({ length: 40 }, (_, i) => ({ id: "UK:" + i }));
  const key = (u) => u.id;
  const a = drawSample(users, 12, "7", key), b = drawSample(users.slice().reverse(), 12, "7", key);
  assert.equal(a.length, 12);
  assert.equal(new Set(a.map(key)).size, 12);                       // no repeats
  assert.deepEqual(a.map(key), b.map(key));                         // same seed, same draw, whatever the order
  assert.notDeepEqual(a.map(key), drawSample(users, 12, "8", key).map(key));
  assert.equal(drawSample(users, 50, "7", key).length, 40);         // n beyond the pool gives the pool
  assert.equal(seedHash("7"), seedHash("7")); assert.notEqual(seedHash("7"), seedHash("8"));
});
test("drawSample is roughly uniform over seeds", () => {
  const users = Array.from({ length: 10 }, (_, i) => ({ id: String(i).padStart(2, "0") }));
  const hits = new Array(10).fill(0);
  for (let s = 0; s < 2000; s++) drawSample(users, 3, "s" + s, (u) => u.id).forEach((u) => { hits[+u.id] += 1; });
  hits.forEach((h) => assert.ok(h > 500 && h < 700, "count " + h));  // expected 600 each
});

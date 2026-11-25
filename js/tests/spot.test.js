import test from "node:test";
import assert from "node:assert/strict";
import { dwellRadius, postOffset, orderUsers, nextInCondition } from "../charts/_spot.js";

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

const U = (id, condition, created_at, extra) => Object.assign({ country: "UK", user_id: id, condition, created_at }, extra || {});
const users = [U(1, "ATTENTION", 10), U(2, "PREFERENCE", 30), U(3, "ATTENTION", 30), U(4, "RANDOM", 20), U(5, "ATTENTION", 20, { default_for: "ATTENTION" })];

test("orderUsers: condition order, newest first inside a condition", () => {
  assert.deepEqual(orderUsers(users).map((u) => u.user_id), [4, 3, 5, 1, 2]);   // RANDOM, ATTENTION (30, 20, 10), PREFERENCE
});
test("nextInCondition cycles through the condition's participants and wraps", () => {
  const att = users.filter((u) => u.condition === "ATTENTION");
  let cur = users[3];                                               // a RANDOM participant is selected
  cur = nextInCondition(users, cur, "ATTENTION");
  assert.equal(cur.user_id, 5);                                     // switching condition: the default pick first
  const seq = [];
  for (let i = 0; i < 4; i++) { cur = nextInCondition(users, cur, "ATTENTION"); seq.push(cur.user_id); }
  assert.deepEqual(seq, [1, 3, 5, 1]);                              // the list is 3, 5, 1 (newest first): from 5 on to 1, 3, 5, 1
  assert.equal(att.length, 3);
  assert.equal(nextInCondition(users, users[0], "PREFERENCE").user_id, 2);
  assert.equal(nextInCondition(users, users[0], "RANDOM").user_id, 4);
  assert.equal(nextInCondition(users, users[0], "NOPE"), null);     // no participant: no selection
  assert.equal(nextInCondition(users, users[1], "PREFERENCE").user_id, 2);   // a single participant stays selected
});

import test from "node:test";
import assert from "node:assert/strict";
import { parseCSV, indexRows, inWindow, byCountry, pool, rebin, countBins, coverage, capAt } from "../select.js";

const launch = Date.parse("2026-11-25T08:30:00Z"), bin = 15 * 60000;
const rows = () => indexRows(parseCSV("bin_start,country,status,n\n2026-11-25T08:30:00Z,UK,done,2\n2026-11-25T08:45:00Z,UK,incomplete,3\n2026-11-25T08:45:00Z,DE,done,4\n2026-11-25T09:15:00Z,DE,done,1"), launch, bin);

test("parseCSV makes numbers of the numeric columns", () => {
  const r = rows();
  assert.equal(r.length, 4); assert.equal(r[0].n, 2); assert.equal(typeof r[0].n, "number"); assert.equal(r[0].status, "done");
});
test("indexRows gives the bin index from the launch", () => {
  assert.deepEqual(rows().map((r) => r.idx), [0, 1, 1, 3]);
});
test("created window is [from, to) in bins", () => {
  const w = { from: 1, to: 3, launchMs: launch, binMs: bin };
  assert.deepEqual(inWindow(rows(), "created", w).map((r) => r.idx), [1, 1]);
});
test("event window uses the time of the row", () => {
  const ev = indexRows(parseCSV("bin_start,country,n\n2026-11-25T08:50:00Z,UK,1\n2026-11-25T09:00:00Z,UK,2\n2026-11-25T09:05:00Z,UK,3"), launch, 5 * 60000);
  const w = { from: 1, to: 2, launchMs: launch, binMs: bin }; // 08:45 to 09:00
  assert.deepEqual(inWindow(ev, "event", w).map((r) => r.n), [1]);
});
test("All pools countries by summing, a country keeps its rows", () => {
  const r = rows();
  assert.deepEqual(pool(byCountry(r, "All"), ["status"], ["n"]).sort((a, b) => a.status.localeCompare(b.status)), [{ status: "done", n: 7 }, { status: "incomplete", n: 3 }]);
  assert.deepEqual(pool(byCountry(r, "DE"), ["status"], ["n"]), [{ status: "done", n: 5 }]);
});
test("rebin sums bins into wider bins", () => {
  const out = rebin(rows(), launch, 60 * 60000, [], ["n"]);
  assert.deepEqual(out, [{ bin: 0, n: 10 }]);
});
test("capAt shares the open last bin", () => { assert.equal(capAt(7, 4), 4); assert.equal(capAt(2, 4), 2); });
test("countBins reaches the last row and the pull time", () => {
  assert.equal(countBins(rows(), launch, bin, launch + 10 * 60000), 4);
  assert.equal(countBins([], launch, bin, launch - 1000), 0);
});
test("coverage lists countries without data and older data", () => {
  const info = { as_of: { UK: "2026-11-25T10:00:00Z", DE: "2026-11-25T09:00:00Z" } };
  assert.deepEqual(coverage(info, ["UK", "DE", "FR"], "All", "2026-11-25T10:00:00Z"), { missing: ["FR"], older: { DE: "2026-11-25T09:00:00Z" } });
  assert.deepEqual(coverage(info, ["UK", "DE", "FR"], "UK", "2026-11-25T10:00:00Z"), { missing: [], older: {} });
});

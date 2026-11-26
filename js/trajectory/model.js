/* Positions and values of the trajectory panels. Pure: no DOM, tested with node --test.

   An attempt is the record of pipeline/trajectory.py. A request has signal_batch t (the batch whose signals it
   carried) and serves batch t + 2 (the last of its batches). The alignment mode selects which of the two gives the
   x position of its reward and profile:
     informed  x = signal_batch: column t is the batch whose signals produced the profile
     informs   x = served batch: column t is the batch that the profile chose */

export const MODES = [
  { key: "informed", label: "informed by", sentence: "Column t of panels 3 to 6 comes from the signals of batch t: the posts of batch t produced this reward, u_short and u_long." },
  { key: "informs", label: "informs", sentence: "Column t of panels 3 to 6 is the profile that chose batch t: this u_long chose the posts of batch t, and the reward and u_short that built it come from the signals of batch t - 2." },
];

export const servedBatch = (e) => (e.batches && e.batches.length ? e.batches[e.batches.length - 1].batch : null);

/** x of a request's reward and profile, or null when it has none in this mode (the init request chose no batch
    by a profile and carries no signals). */
export function xOf(e, mode) {
  if (e.endpoint === "init") return null;
  return mode === "informed" ? (e.signal_batch == null ? null : e.signal_batch) : servedBatch(e);
}

export function profileColumns(attempt, mode) {
  return attempt.exchanges.map((e) => ({ x: xOf(e, mode), e })).filter((q) => q.x != null).sort((a, b) => a.x - b.x);
}

/** Served batches in order: [{batch, b, e}] with b the batch record and e the request that served it. */
export function batchList(attempt) {
  return attempt.exchanges.flatMap((e) => e.batches.map((b) => ({ batch: b.batch, b, e }))).sort((a, b) => a.batch - b.batch);
}

export const maxBatch = (attempt) => Math.max(1, ...batchList(attempt).map((q) => q.batch));

/** The last batch of the init and warm-up requests, or null. */
export function warmEnd(attempt) {
  const w = batchList(attempt).filter((q) => q.e.endpoint === "init" || q.e.phase === "warmup").map((q) => q.batch);
  return w.length ? Math.max(...w) : null;
}

/** The request that carried the signals of a batch, or null. */
export const signalsOf = (attempt, batch) => attempt.exchanges.find((e) => e.signal_batch === batch) || null;

/** Which parts of a record exist: files written before the trajectory panels lack some. */
export function available(attempt) {
  const batches = batchList(attempt);
  return {
    signalBatch: attempt.exchanges.some((e) => "signal_batch" in e),
    batchMeans: batches.some((q) => q.b.mean_centered != null),
    rewards: attempt.exchanges.some((e) => "rewards" in e),
    uShort: attempt.exchanges.some((e) => "u_short" in e),
  };
}

/** Mean over the posts that have a reward; null when none has one. */
export function rewardMean(rewards) {
  const v = (rewards || []).filter((r) => r != null);
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
}

/** One y range for the panels in centered score units (batch means, u_short, u_long), always including 0. */
export function centeredRange(attempt) {
  const v = [0];
  batchList(attempt).forEach((q) => v.push(...(q.b.mean_centered || [])));
  attempt.exchanges.forEach((e) => v.push(...(e.u_short || []), ...(e.u_long || [])));
  return paddedRange(v);
}

export function paddedRange(values) {
  const v = values.filter((x) => x != null && Number.isFinite(x));
  const lo = Math.min(0, ...v), hi = Math.max(0, ...v), span = hi - lo || 1;
  return { lo: lo - 0.08 * span, hi: hi + 0.08 * span };
}

/** About n ticks inside [lo, hi] in steps of 1, 2 or 5 x 10^k. */
export function niceTicks(lo, hi, n) {
  const raw = (hi - lo) / Math.max(1, n || 4), p = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 5, 10].map((s) => s * p).find((s) => s >= raw);
  const out = [];
  for (let k = Math.ceil(lo / step); k * step <= hi + 1e-9; k++) out.push(+(k * step).toFixed(10));
  return out;
}

/** Runs of consecutive columns, so that a line is not drawn across a gap. points: [{x, y}] sorted by x. */
export function segments(points) {
  const out = [];
  points.forEach((p) => {
    const last = out[out.length - 1];
    if (last && p.x - last[last.length - 1].x <= 1) last.push(p); else out.push([p]);
  });
  return out;
}

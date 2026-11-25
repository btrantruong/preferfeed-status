/* Shared helpers of the event charts: a regular grid of event bins over the window. */
import { linear } from "../svg.js";

/** Grid of bins [t0, t1) in steps of eventMs: {t0, nBins}; the window edges lie on bin edges. */
export function grid(c) {
  const nBins = Math.max(1, Math.round((c.t1 - c.t0) / c.eventMs));
  return { t0: c.t0, nBins, binMs: c.eventMs };
}

/** Values per bin for the rows matching `pred`, summing n. */
export function series(rows, g, pred, key) {
  const v = new Array(g.nBins).fill(0);
  rows.forEach((r) => {
    if (pred && !pred(r)) return;
    const k = Math.floor((r.t - g.t0) / g.binMs);
    if (k >= 0 && k < g.nBins) v[k] += key ? r[key] : r.n;
  });
  return v;
}

export const sum = (a) => a.reduce((x, y) => x + y, 0);
export { linear };

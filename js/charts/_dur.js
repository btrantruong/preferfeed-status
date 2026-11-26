/* Shared by ss2 and ss3: labels of the duration bins and summaries read from a histogram (pure, tested with node --test). */

/** Bin k of a duration is 0 below edges[0], k from edges[k-1] on, edges.length from the last edge on (see cubes.dur_bin). */
export function durLabels(edges) {
  const fmt = (s) => (s < 60 ? s + " s" : s % 60 === 0 ? s / 60 + " min" : (s / 60).toFixed(1) + " min");
  const short = [], range = [];
  for (let k = 0; k <= edges.length; k++) {
    if (k === 0) { short.push("<" + fmt(edges[0]).replace(" ", "")); range.push("under " + fmt(edges[0])); }
    else if (k === edges.length) { short.push(">" + (edges[k - 1] / 60)); range.push(fmt(edges[k - 1]) + " or more"); }
    else { short.push("<" + (edges[k] % 60 === 0 ? edges[k] / 60 : fmt(edges[k]))); range.push(fmt(edges[k - 1]) + " to under " + fmt(edges[k])); }
  }
  return { short, range };
}

/** Median in minutes estimated from counts per bin (linear inside a bin; the open last bin gives its lower edge). */
export function histMedian(counts, edges) {
  const total = counts.reduce((a, b) => a + b, 0);
  if (!total) return null;
  const lo = (k) => (k === 0 ? 0 : edges[k - 1] / 60), hi = (k) => (k < edges.length ? edges[k] / 60 : null);
  let acc = 0;
  for (let k = 0; k < counts.length; k++) {
    if (acc + counts[k] >= total / 2) {
      if (hi(k) == null || !counts[k]) return lo(k);
      return lo(k) + ((total / 2 - acc) / counts[k]) * (hi(k) - lo(k));
    }
    acc += counts[k];
  }
  return lo(counts.length - 1);
}

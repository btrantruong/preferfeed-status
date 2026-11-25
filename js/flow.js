/* Flow (Sankey-like) layout for se2. Pure functions (tested with node --test).

   Input: transitions [{step, from, to, n}] where step k holds the participants whose k-th error run is `to`
   (from is the node of run k-1, or START for k = 0, and END marks a log that ended). Column k shows the
   nodes `to` of step k, with height proportional to participants. Bands join column k-1 to column k. */

export const START = "START", END = "END";

/** Columns of nodes: [{node, n}] per step, ordered by `order`; END last. */
export function columns(transitions, steps, order) {
  const cols = [];
  for (let k = 0; k < steps; k++) {
    const m = new Map();
    transitions.filter((t) => t.step === k).forEach((t) => m.set(t.to, (m.get(t.to) || 0) + t.n));
    const nodes = [...m.entries()].map(([node, n]) => ({ node, n }));
    const rank = (x) => (x === END ? 1e9 : order.indexOf(x) < 0 ? 1e8 : order.indexOf(x));
    nodes.sort((a, b) => rank(a.node) - rank(b.node));
    cols.push(nodes);
  }
  return cols;
}

/** Positions: scale = pixels per participant, gap in pixels. Returns {nodes: {"k|node": {k,node,n,y,h}}, height}. */
export function layout(cols, scale, gap) {
  const nodes = {}; let height = 0;
  cols.forEach((col, k) => {
    let y = 0;
    col.forEach((c) => {
      const hgt = Math.max(c.n * scale, c.n > 0 ? 1 : 0);
      nodes[k + "|" + c.node] = { k, node: c.node, n: c.n, y, h: hgt };
      y += hgt + gap;
    });
    height = Math.max(height, y - gap);
  });
  return { nodes, height };
}

/** Bands between columns: [{k, from, to, n, y0, y1, h}] with the vertical stacking inside each node. */
export function bands(transitions, lay, scale) {
  const outOff = {}, inOff = {}, out = [];
  const order = (a, b) => a.k - b.k || (lay.nodes[(a.k - 1) + "|" + a.from] ? lay.nodes[(a.k - 1) + "|" + a.from].y : 0) - (lay.nodes[(b.k - 1) + "|" + b.from] ? lay.nodes[(b.k - 1) + "|" + b.from].y : 0)
    || (lay.nodes[a.k + "|" + a.to] ? lay.nodes[a.k + "|" + a.to].y : 0) - (lay.nodes[b.k + "|" + b.to] ? lay.nodes[b.k + "|" + b.to].y : 0);
  transitions.filter((t) => t.step >= 1 && t.from !== START).map((t) => ({ k: t.step, from: t.from, to: t.to, n: t.n })).sort(order).forEach((t) => {
    const a = lay.nodes[(t.k - 1) + "|" + t.from], b = lay.nodes[t.k + "|" + t.to];
    if (!a || !b) return;
    const ka = (t.k - 1) + "|" + t.from, kb = t.k + "|" + t.to;
    const h = t.n * scale;
    const y0 = a.y + (outOff[ka] || 0), y1 = b.y + (inOff[kb] || 0);
    outOff[ka] = (outOff[ka] || 0) + h; inOff[kb] = (inOff[kb] || 0) + h;
    out.push({ k: t.k, from: t.from, to: t.to, n: t.n, y0, y1, h });
  });
  return out;
}

/** Pixels per participant so that the tallest column fits `maxHeight` with `gap` between nodes. */
export function fitScale(cols, maxHeight, gap) {
  let s = Infinity;
  cols.forEach((col) => {
    const total = col.reduce((a, c) => a + c.n, 0);
    if (total > 0) s = Math.min(s, (maxHeight - gap * (col.length - 1)) / total);
  });
  return Number.isFinite(s) ? Math.max(s, 0) : 0;
}

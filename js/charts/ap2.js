/* C2. Warm-up exit: share of next_batch exchanges in phase algorithm, by request index and condition. */
import { barPlot } from "../plots.js";
import { pool } from "../select.js";
import { COND, lc } from "../colors.js";
import { h } from "../util.js";

export default {
  id: "ap2", title: "Warm-up exit", files: ["warmup.csv"], window: "created",
  caption: (m) => "x: request_index of the final attempt (1 to " + ((m.params || {}).warmup_max_index || 10) + "). y: share of next_batch exchanges of attention and preference participants whose algo_state.phase is algorithm (the profile is used), in percent, one plot per condition; the number of exchanges at each index is printed under the axis. Participants created inside the window, countries as selected above. The phase is used because on algorithm version 0.1.3 the client sends the assigned condition from the first next_batch on, so the algorithm type no longer switches from RANDOM.",
  how: "Shows at which batch index participants leave the warm-up. If no exchange is in phase algorithm, the warm-up lasts longer than the indices shown or the phase is not stored.",
  draw(box, c) {
    box.replaceChildren();
    const mx = c.p.warmup_max_index || 10, rows = c.rows("warmup.csv");
    const conds = ["ATTENTION", "PREFERENCE"].filter((k) => rows.some((r) => r.condition === k));
    if (!conds.length) { box.append(h("div", { class: "empty" }, "No attention or preference participant with next_batch exchanges in this time range.")); return; }
    const grid = h("div", { class: "grid2" }); box.append(grid);
    let anyAlgo = 0;
    conds.forEach((k) => {
      const m = new Map(pool(rows.filter((r) => r.condition === k), ["request_index"], ["n", "n_algorithm"]).map((r) => [r.request_index, r]));
      const xs = []; for (let v = 1; v <= mx; v++) xs.push(v);
      const n = xs.map((v) => (m.get(v) || { n: 0 }).n), a = xs.map((v) => (m.get(v) || { n_algorithm: 0 }).n_algorithm);
      anyAlgo += a.reduce((x, y) => x + y, 0);
      const cell = h("div", {}, h("p", { class: "small-title" }, lc(k))); const sub = h("div", { class: "chart sub" }); cell.append(sub); grid.append(cell);
      barPlot(sub, { labels: xs.map(String), height: 190, margin: { l: 44, t: 6, b: 38 }, ticks: { step: 50, max: 100, ticks: [0, 50, 100] }, fmtY: (t) => t + "%", gap: 0.15, minLabelPx: 1,
        series: [{ name: "algorithm", color: COND[k], values: n.map((x, i) => (x ? (100 * a[i]) / x : 0)) }],
        tip: (i) => "<b>request " + xs[i] + "</b><br>" + a[i] + " of " + n[i] + " exchanges in phase algorithm" });
      const counts = h("div", { class: "how" }, "n per index: " + n.join(", ")); cell.append(counts);
    });
    if (!anyAlgo) box.append(h("div", { class: "cov" }, "No exchange is in phase algorithm in this selection."));
  },
};

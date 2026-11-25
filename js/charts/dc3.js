/* B3. Requests per participant, by condition, and against viewed_posts / batch size. */
import { barPlot } from "../plots.js";
import { pool } from "../select.js";
import { CONDITIONS, COND, lc } from "../colors.js";
import { h } from "../util.js";

export default {
  id: "dc3", group: "Data completeness", title: "Requests per participant", files: ["requests_hist.csv", "requests_diff_hist.csv"], window: "created",
  caption: (m) => "Left: x is request_index max + 1 of the final attempt (algorithm requests including init; the last bar holds " + ((m.params || {}).requests_max || 40) + " and more); y is the number of done participants created inside the window, one plot per condition. Right: x is that number minus visited_users.viewed_posts / " + ((m.params || {}).batch_size || 5) + " (posts per batch), rounded to integers with open ends at +-" + ((m.params || {}).diff_range || 10) + "; the dashed line is 0.",
  how: "Compare the requests with viewed_posts / batch size. A mismatch points to lost or doubled requests.",
  draw(box, c) {
    box.replaceChildren();
    const rmax = c.p.requests_max || 40, dr = c.p.diff_range || 10, grid = h("div", { class: "grid2" }); box.append(grid);
    const reqRows = c.rows("requests_hist.csv"), diffRows = c.rows("requests_diff_hist.csv");
    const present = CONDITIONS.filter((k) => reqRows.some((r) => r.condition === k) || diffRows.some((r) => r.condition === k));
    if (!present.length) { box.append(h("div", { class: "empty" }, "No done participants in this time range.")); return; }
    present.forEach((k) => {
      const a = h("div", {}, h("p", { class: "small-title" }, lc(k) + " · requests")); const ba = h("div", { class: "chart sub" }); a.append(ba);
      const b = h("div", {}, h("p", { class: "small-title" }, lc(k) + " · requests minus viewed posts / " + (c.p.batch_size || 5))); const bb = h("div", { class: "chart sub" }); b.append(bb);
      grid.append(a, b);
      const ra = pool(reqRows.filter((r) => r.condition === k), ["requests"], ["n"]); const ma = new Map(ra.map((r) => [r.requests, r.n]));
      const xs = []; for (let v = 1; v <= rmax; v++) xs.push(v);
      barPlot(ba, { labels: xs.map((v) => (v % 5 === 0 ? String(v) + (v === rmax ? "+" : "") : "")), height: 140, margin: { l: 40, t: 6 }, gap: 0.1, minLabelPx: 1,
        series: [{ name: "done", color: COND[k], values: xs.map((v) => ma.get(v) || 0) }],
        tip: (i) => "<b>" + xs[i] + (xs[i] === rmax ? " or more" : "") + " requests</b><br>" + (ma.get(xs[i]) || 0) + " done participants" });
      const rb = pool(diffRows.filter((r) => r.condition === k), ["diff"], ["n"]); const mb = new Map(rb.map((r) => [r.diff, r.n]));
      const ds = []; for (let v = -dr; v <= dr; v++) ds.push(v);
      barPlot(bb, { labels: ds.map((v) => (v % 5 === 0 ? (v > 0 ? "+" : "") + v : "")), height: 140, margin: { l: 40, t: 6 }, gap: 0.1, minLabelPx: 1, ref: dr,
        series: [{ name: "done", color: COND[k], values: ds.map((v) => mb.get(v) || 0) }],
        tip: (i) => "<b>" + (ds[i] > 0 ? "+" : "") + ds[i] + (Math.abs(ds[i]) === dr ? " or beyond" : "") + "</b><br>" + (mb.get(ds[i]) || 0) + " done participants" });
    });
  },
};

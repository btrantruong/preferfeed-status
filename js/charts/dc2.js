/* D2. Records per done participant. */
import { barPlot } from "../plots.js";
import { pool } from "../select.js";

export default {
  id: "dc2", title: "Records per done participant", files: ["records_hist.csv"], window: "created",
  caption: (m) => "x: number of record_entry rows of the participant's final attempt, in bins of " + ((m.params || {}).records_bin_width || 2000) + " rows with a separate bar for exactly 0 and an open last bin from " + ((m.params || {}).records_max || 50000) + ". y: number of done participants created inside the window, for the countries selected above.",
  how: "A spike at 0 or at very low counts means data was lost. Rows are written about 40 per focused second while the feed is open, so a low count can also come from a short session.",
  draw(box, c) {
    const w = c.p.records_bin_width || 2000, mx = c.p.records_max || 50000;
    const edges = [0, 1]; for (let e = w; e <= mx; e += w) edges.push(e);
    const rows = pool(c.rows("records_hist.csv"), ["records_bin"], ["n"]);
    const m = new Map(rows.map((r) => [r.records_bin, r.n]));
    const vals = edges.map((e) => m.get(e) || 0);
    const total = vals.reduce((a, b) => a + b, 0);
    const kfmt = (e) => (e === 0 ? "0" : e === 1 ? "1" : e >= 1000 ? (e / 1000) + "k" : String(e));
    const range = (i) => (edges[i] === 0 ? "exactly 0" : edges[i] === 1 ? "1 to " + (w - 1) : edges[i] >= mx ? mx + " or more" : edges[i] + " to " + (edges[i] + w - 1));
    barPlot(box, { labels: edges.map((e, i) => (i === 0 || (e >= w && (e / w) % 5 === 0) ? kfmt(e) + (e >= mx ? "+" : "") : "")), height: 210, ylabel: "Done participants", gap: 0.12, minLabelPx: 1,
      series: [{ name: "done", color: "--c1", values: vals }],
      tip: (i) => "<b>" + range(i) + " rows</b><br>" + vals[i] + " done participants" });
    const x = document.createElement("div"); x.className = "extra how"; x.textContent = total + " done participants; " + (vals[0] || 0) + " with 0 rows."; box.append(x);
  },
};

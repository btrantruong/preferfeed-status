/* B2. Time spent on the feed, done versus not done. */
import { barPlot } from "../plots.js";
import { pool } from "../select.js";
import { legend } from "../svg.js";
import { durLabels, histMedian } from "./_dur.js";
import { css } from "../util.js";

const GROUPS = [["done", "done", "--s-done"], ["not_done", "not done", "--text-muted"]];

export default {
  id: "ss2", title: "Time on the feed", files: ["time_on_feed_hist.csv"], window: "created",
  caption: (m) => "x: time on the feed in bins whose edges are " + (((m.params || {}).duration_edges_s) || []).join(", ") + " seconds (the first bin is below the first edge, the last bin is open). y: participants created inside the window, stacked by done and not done. Left: the final attempt, from its init exchange to its last behaviour record. Right: the total over all attempts (the sum of the attempt durations; time between attempts is not counted). Participants without a behaviour record are not in the bars.",
  how: "Not-done participants far to the left left the feed early. A done participant's final attempt is close to the 10 minutes of the timeline; a longer total comes from earlier attempts. Medians are read from the bins and are approximate; means use the exact sums.",
  draw(box, c) {
    const edges = (c.p.duration_edges_s || []).slice(), L = durLabels(edges), n = L.short.length;
    const all = c.rows("time_on_feed_hist.csv");
    box.replaceChildren();
    const grid = document.createElement("div"); grid.className = "grid2 sub"; box.append(grid);
    const notes = [];
    [["final_attempt", "Final attempt"], ["total", "All attempts (total)"]].forEach(([measure, title]) => {
      const rows = pool(all.filter((r) => r.measure === measure), ["group", "dur_bin"], ["n", "sum_min"]);
      const get = (g, k, f) => rows.filter((r) => r.group === g && r.dur_bin === k).reduce((a, r) => a + r[f], 0);
      const series = GROUPS.map(([g, name, color]) => ({ name, color, values: [...Array(n).keys()].map((k) => get(g, k, "n")) }));
      const cell = document.createElement("div"); cell.innerHTML = '<p class="small-title">' + title + "</p>";
      const sub = document.createElement("div"); sub.className = "chart"; sub.style.position = "relative"; cell.append(sub); grid.append(cell);
      barPlot(sub, { labels: L.short, series, height: 200, ylabel: "Participants", margin: { l: 44 }, minLabelPx: 22, gap: 0.12,
        tip: (i) => "<b>" + L.range[i] + "</b>" + series.map((s) => "<br>" + s.name + ": " + s.values[i]).join("") });
      GROUPS.forEach(([g, name]) => {
        const v = series[GROUPS.findIndex((x) => x[0] === g)].values, cnt = v.reduce((a, b) => a + b, 0);
        const sum = [...Array(n).keys()].reduce((a, k) => a + get(g, k, "sum_min"), 0), med = histMedian(v, edges);
        notes.push(title + ", " + name + ": " + cnt + " participants" + (cnt ? ", mean " + (sum / cnt).toFixed(1) + " min, median about " + med.toFixed(1) + " min" : ""));
      });
    });
    const x = document.createElement("div"); x.className = "extra";
    x.innerHTML = legend(GROUPS.map(([, name, color]) => ({ label: name, color: css(color) }))) + '<p class="how">' + notes.join("<br>") + "</p>";
    box.append(x);
  },
};

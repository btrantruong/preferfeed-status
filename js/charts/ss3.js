/* B5. Duration of each attempt, by attempt number and how the attempt ended. */
import { barPlot } from "../plots.js";
import { pool } from "../select.js";
import { legend } from "../svg.js";
import { durLabels, histMedian } from "./_dur.js";
import { css } from "../util.js";

const ENDS = [["restarted", "restarted", "--c7"], ["done", "done", "--s-done"], ["cancelled", "cancelled", "--s-cancelled"], ["incomplete", "incomplete", "--text-muted"]];

export default {
  id: "ss3", group: "Sessions", title: "Attempt durations", files: ["attempts_hist.csv"], window: "created",
  caption: (m) => "x: duration of one attempt (from its init exchange to its last behaviour record), in bins whose edges are " + (((m.params || {}).duration_edges_s) || []).join(", ") + " seconds (the first bin is below the first edge, the last bin is open). y: attempts of participants created inside the window, one plot per attempt number (the last plot holds that number and higher), stacked by how the attempt ended: restarted (the participant started again), or the final status of the participant for their last attempt. Each attempt is counted once.",
  how: "Attempts that ended in a restart are mostly short. A participant's last attempt is incomplete when they left without being stopped.",
  draw(box, c) {
    const edges = (c.p.duration_edges_s || []).slice(), L = durLabels(edges), n = L.short.length, max = c.p.attempts_max || 4;
    const rows = pool(c.rows("attempts_hist.csv"), ["attempt_no", "ends_as", "dur_bin"], ["n", "sum_min"]);
    box.replaceChildren();
    const grid = document.createElement("div"); grid.className = "grid2 sub"; box.append(grid);
    const notes = [];
    for (let a = 1; a <= max; a++) {
      const sel = rows.filter((r) => r.attempt_no === a);
      const get = (e, k) => sel.filter((r) => r.ends_as === e && r.dur_bin === k).reduce((s, r) => s + r.n, 0);
      const series = ENDS.map(([e, name, color]) => ({ name, color, values: [...Array(n).keys()].map((k) => get(e, k)) }));
      const per = [...Array(n).keys()].map((k) => series.reduce((s, x) => s + x.values[k], 0));
      const total = per.reduce((s, v) => s + v, 0);
      const title = a === max ? "Attempt " + a + " and higher" : "Attempt " + a;
      const cell = document.createElement("div"); cell.innerHTML = '<p class="small-title">' + title + "</p>";
      const sub = document.createElement("div"); sub.className = "chart"; sub.style.position = "relative"; cell.append(sub); grid.append(cell);
      barPlot(sub, { labels: L.short, series, height: 170, ylabel: "Attempts", margin: { l: 44 }, minLabelPx: 22, gap: 0.12,
        tip: (i) => "<b>" + title + ", " + L.range[i] + "</b>" + series.map((s) => "<br>" + s.name + ": " + s.values[i]).join("") });
      const restarted = series[0].values, nr = restarted.reduce((s, v) => s + v, 0);
      notes.push(title + ": " + total + " attempts" + (nr ? "; the " + nr + " that ended in a restart have a median of about " + histMedian(restarted, edges).toFixed(1) + " min" : ""));
    }
    const x = document.createElement("div"); x.className = "extra";
    x.innerHTML = legend(ENDS.map(([, name, color]) => ({ label: name, color: css(color) }))) + '<p class="how">' + notes.join("<br>") + "</p>";
    box.append(x);
  },
};

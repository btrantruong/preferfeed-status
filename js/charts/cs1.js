/* A1. Condition balance: participants who started and who finished, per condition. */
import { barPlot } from "../plots.js";
import { COND, CONDITIONS, lc } from "../colors.js";
import { pool } from "../select.js";
import { pct0 } from "../util.js";

export default {
  id: "cs1", title: "Condition balance", files: ["status_detail.csv"], window: "created",
  caption: () => "x: condition as stored in visited_users.condition. y: participants who started (pale bar; visited_users.started) and who finished (solid bar; done, as on the status page), created inside the window, for the countries selected above. The finish share and the number of participants who started are printed above each pair.",
  how: "A lopsided finish rate across conditions means attrition differs by arm. That is a design issue, separate from errors.",
  draw(box, c) {
    const rows = pool(c.rows("status_detail.csv"), ["condition", "started", "status"], ["n"]);
    const seen = new Set(rows.map((r) => r.condition));
    const conds = CONDITIONS.filter((k) => seen.has(k)).concat(seen.has("unknown") ? ["unknown"] : []);
    const started = conds.map((k) => rows.filter((r) => r.condition === k && r.started === 1).reduce((a, r) => a + r.n, 0));
    const done = conds.map((k) => rows.filter((r) => r.condition === k && r.status === "done").reduce((a, r) => a + r.n, 0));
    if (!conds.length) { barPlot(box, { labels: ["none"], series: [{ name: "started", color: "--grid", values: [0] }], height: 120 }); return; }
    // one bar group per condition: started and finished side by side, in the condition's color
    const labels = conds.map(lc);
    barPlot(box, {
      labels, stacked: false, height: 210, ylabel: "Participants",
      series: [{ name: "started", color: "--text-muted", values: started, opacity: 0.35 }, { name: "finished", color: "--accent", values: done }],
      colorOf: (j, i) => COND[conds[i]],
      topLabel: (i) => pct0(done[i], started[i]) + " of " + started[i],
      tip: (i) => "<b>" + labels[i] + "</b><br>started: " + started[i] + "<br>finished: " + done[i] + " (" + pct0(done[i], started[i]) + ")",
    });
    const legend = document.createElement("div"); legend.className = "legend extra";
    legend.innerHTML = '<span><span class="sw" style="background:var(--text-muted);opacity:.35"></span>started (pale)</span><span><span class="sw" style="background:var(--text-muted)"></span>finished (solid); the color is the condition</span>' +
      conds.map((k) => '<span><span class="sw" style="background:var(' + COND[k] + ')"></span>' + lc(k) + "</span>").join("");
    box.appendChild(legend);
  },
};

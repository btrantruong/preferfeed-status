/* A2. Retaking attempts per participant. */
import { barPlot } from "../plots.js";
import { STATUS, STATUS_LABEL } from "../colors.js";
import { pool } from "../select.js";
import { legend } from "../svg.js";
import { css } from "../util.js";

const STATUSES = ["done", "cancelled", "incomplete"];

export default {
  id: "cs2", title: "Retaking attempts per participant", files: ["attempts.csv"], window: "created",
  caption: () => "x: retakes per participant, the number of timeline starts minus 1 (the last bar holds this many starts and more). y: participants, stacked by status at the last pull, created inside the window. Left: all participants with a recorded start. Right, on its own scale: participants who retook after a stop (at least two starts and a stop code, bot, idle or reload, logged before the last start). Starts come from visited_users.attempt, or from the number of init exchanges where that column does not exist.",
  how: "A restart is allowed after a stop and sets the status back to incomplete, so the stop in the log and the recorded attempt identify a retake. A participant who is done cannot start again (logged as a duplicate attempt, not a retake).",
  draw(box, c) {
    const max = c.p.attempts_max || 4;
    const rows = pool(c.rows("attempts.csv"), ["attempts", "after_stop", "status"], ["n"]);
    const noStart = rows.filter((r) => r.attempts === 0).reduce((a, r) => a + r.n, 0);
    const started = rows.filter((r) => r.attempts >= 1);
    const label = (k) => (k >= max - 1 ? (max - 1) + "+" : String(k));
    const mk = (src, ks) => ({
      labels: ks.map(label),
      series: STATUSES.map((s) => ({ name: STATUS_LABEL[s], color: STATUS[s],
        values: ks.map((k) => src.filter((r) => Math.min(r.attempts - 1, max - 1) === k && r.status === s).reduce((a, r) => a + r.n, 0)) })),
    });
    box.replaceChildren();
    const grid = document.createElement("div"); grid.className = "grid2 sub"; box.append(grid);
    const parts = [
      { title: "All participants with a timeline start", src: started, ks: [...Array(max).keys()] },
      { title: "Retook after a stop (own y scale)", src: started.filter((r) => r.after_stop === 1 && r.attempts >= 2), ks: [...Array(max - 1).keys()].map((k) => k + 1) },
    ];
    parts.forEach((p) => {
      const cell = document.createElement("div"); cell.innerHTML = '<p class="small-title">' + p.title + "</p>";
      const sub = document.createElement("div"); sub.className = "chart"; sub.style.position = "relative"; cell.append(sub); grid.append(cell);
      const d = mk(p.src, p.ks);
      barPlot(sub, { labels: d.labels, series: d.series, height: 190, ylabel: "Participants", margin: { l: 48 },
        topLabel: (i, t) => (t ? String(t) : ""), tip: (i) => "<b>" + d.labels[i] + " retakes</b>" + d.series.map((s) => "<br>" + s.name + ": " + s.values[i]).join("") });
    });
    const total = started.reduce((a, r) => a + r.n, 0);
    const retook = started.filter((r) => r.attempts >= 2).reduce((a, r) => a + r.n, 0);
    const afterStop = started.filter((r) => r.attempts >= 2 && r.after_stop === 1).reduce((a, r) => a + r.n, 0);
    const x = document.createElement("div"); x.className = "extra";
    x.innerHTML = legend(STATUSES.map((s) => ({ label: STATUS_LABEL[s], color: css(STATUS[s]) }))) +
      '<p class="how">' + total + " participants with a recorded start; " + retook + " retook, " + afterStop + " of them after a stop and " + (retook - afterStop) +
      " without a logged stop (not in the right plot). " + noStart + " participants have no recorded start and are not in the bars.</p>";
    box.append(x);
  },
};

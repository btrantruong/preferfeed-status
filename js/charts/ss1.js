/* B1. In session or left: the state of the participants at the last pull, by condition. */
import { barPlot } from "../plots.js";
import { CONDITIONS, lc } from "../colors.js";
import { pool } from "../select.js";
import { legend } from "../svg.js";
import { css, pct } from "../util.js";

const STATES = [["done", "done", "--s-done"], ["stopped", "stopped (cancelled)", "--s-cancelled"], ["in_session", "in session", "--c3"], ["left", "left", "--text-muted"]];

export default {
  id: "ss1", title: "In session or left", files: ["session_state.csv"], window: "created",
  caption: (m) => {
    const s = m.sessions, rule = (m.params || {}).session_rule === "silence" ? "silence" : "time";
    const ref = s ? "T_ref is " + s.t_ref_min.toFixed(1) + " minutes (" + (s.source === "launch" ? "the " + Math.round((((m.params || {}).session_ref_quantile) || 0.95) * 100) + "th percentile of entry to last record of " + s.n + " done participants" : "the fixed design length of the timeline, because fewer than the required number of participants are done") + ")" : "";
    return "x: condition. y: participants created inside the window, stacked by state at the last pull. done and stopped (cancelled) come from the study status. Of the others, in session means the time since entry (creation, or the last start after a restart) is below T_ref, and left means it is not; " + ref + ". The silence rule (the last behaviour record at most " + ((m.params || {}).session_silence_s || 90) + " s old) is computed too; the rule shown is " + rule + ".";
  },
  how: "A participant counted as left has not been done or stopped by the software and has been away longer than a normal session. A restart starts a new session and counts the time from the last start. T_ref changes as more participants finish.",
  draw(box, c) {
    const rows = pool(c.rows("session_state.csv"), ["condition", "state"], ["n", "n_disagree"]);
    const conds = CONDITIONS.concat(rows.map((r) => r.condition).filter((x) => !CONDITIONS.includes(x))).filter((x, i, a) => a.indexOf(x) === i);
    const labels = conds.map((x) => lc(x)).concat(["all"]);
    const val = (cond, st) => rows.filter((r) => (cond === "all" || r.condition === cond) && r.state === st).reduce((a, r) => a + r.n, 0);
    const series = STATES.map(([k, name, color]) => ({ name, color, values: conds.concat(["all"]).map((cnd) => val(cnd, k)) }));
    const dis = rows.reduce((a, r) => a + r.n_disagree, 0);
    box.replaceChildren();
    const sub = document.createElement("div"); sub.className = "chart sub"; sub.style.position = "relative"; box.append(sub);
    barPlot(sub, { labels, series, height: 230, ylabel: "Participants", margin: { l: 48 }, minLabelPx: 40, topLabel: (i, t) => (t ? String(t) : ""),
      tip: (i) => "<b>" + labels[i] + "</b>" + series.map((s) => "<br>" + s.name + ": " + s.values[i] + " (" + pct(s.values[i], series.reduce((a, x) => a + x.values[i], 0)) + ")").join("") });
    const x = document.createElement("div"); x.className = "extra";
    const tot = series.reduce((a, s) => a + s.values[labels.length - 1], 0);
    x.innerHTML = legend(STATES.map(([, name, color]) => ({ label: name, color: css(color) }))) +
      '<p class="how">' + tot + " participants; " + dis + " of them are classified differently by the time rule and the silence rule.</p>";
    box.append(x);
  },
};

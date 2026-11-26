/* A3. Retries: what came before the last restart and how the retried participants ended. */
import { barPlot } from "../plots.js";
import { pool } from "../select.js";
import { legend } from "../svg.js";
import { css, h, pct0 } from "../util.js";
import { ERROR_TYPES, RETRY_OUTCOMES, retryStacks } from "./_outcomes.js";

const PLOT_HEIGHT = 200, NONE = "none";

export default {
  id: "cs2", title: "Retries: what came before and how they ended", files: ["retries.csv", "outcome_bins.csv"], window: "created",
  caption: (m) => {
    const top = ((m.params || {}).attempts_max || 4) - 1;
    return "Only participants who retried (started the timeline again), created inside the window; each counts once in each plot. Top: x is the type of the last error logged in the attempt that the last restart ended (none: nothing was logged in it); an error of an earlier attempt does not count here. Bottom: x is the number of retries (the last bar holds " + top + " and more). y of both: participants, stacked by outcome at the last pull; the last attempt is the one after the last restart. Above each bar: participants and the share of them who are done. Some counted here are listed under error, no retry or still in session in the status figure.";
  },
  how: "It shows which kind of interruption is followed by a finished session, and whether those who left had an error in their last attempt.",
  draw(box, c) {
    box.replaceChildren();
    const rows = pool(c.rows("retries.csv"), ["trigger", "retries", "retry_outcome"], ["n"]);
    const total = c.rows("outcome_bins.csv").reduce((a, r) => a + r.n, 0);
    const retried = rows.reduce((a, r) => a + r.n, 0);
    const summary = h("p", { class: "how" }, retried + " of " + total + " participants in this selection retried.");
    if (!retried) { box.append(h("div", { class: "empty" }, "No participant retried in this time range."), summary); return; }
    const top = (c.p.attempts_max || 4) - 1;
    const triggers = ERROR_TYPES.concat([NONE], rows.map((r) => r.trigger)).filter((t, i, a) => a.indexOf(t) === i);
    const counts = [...Array(top).keys()].map((k) => k + 1);
    const plots = [
      { title: "What came before the last restart", field: "trigger", xs: triggers, labels: triggers, tip: (x) => "before the last restart: " + (x === NONE ? "no logged error" : x) },
      { title: "Number of retries", field: "retries", xs: counts, labels: counts.map((k) => (k === top ? k + "+" : String(k))), tip: (x) => (x === top ? x + " or more" : x) + (x === 1 ? " retry" : " retries") },
    ];
    plots.forEach((p) => {
      const sub = h("div", { class: "chart sub" });
      box.append(h("p", { class: "small-title" }, p.title), sub);
      const series = retryStacks(rows, p.field, p.xs);
      barPlot(sub, { labels: p.labels, series, height: PLOT_HEIGHT, ylabel: "Participants", margin: { l: 48 }, minLabelPx: 36,
        topLabel: (i, t) => (t ? t + " (" + pct0(series[0].values[i], t) + ")" : ""),
        tip: (i) => "<b>" + p.tip(p.xs[i]) + "</b>" + series.map((s) => "<br>" + s.name + ": " + s.values[i]).join("") });
    });
    const x = h("div", { class: "extra" });
    x.innerHTML = legend(RETRY_OUTCOMES.map((o) => ({ label: o.label, color: css(o.color) })));
    box.append(x, summary);
  },
};

/* C3. Where in the session the error happens. */
import { barPlot } from "../plots.js";
import { pool } from "../select.js";
import { h } from "../util.js";

export default {
  id: "se3", group: "Server-side errors", title: "Where in the session the error happens", files: ["errors_age.csv"], window: "created",
  caption: (m) => "x: minutes between the participant's session creation (created_at) and the logged error, in bins of " + ((m.params || {}).error_age_bin_min || 1) + " minute up to " + ((m.params || {}).error_age_max_min || 20) + " (open last bin). y: number of events, one small chart per error code, for participants created inside the window and the countries selected above. created_at is the session creation, before the feed starts, and a retaking participant keeps it, so late events collect in the last bin.",
  how: "Separates failures at startup (init) from failures partway through (next_batch).",
  draw(box, c) {
    box.replaceChildren();
    const bin = c.p.error_age_bin_min || 1, top = (c.p.error_age_max_min || 20) / bin;
    const codes = [c.p.server_error_code || "SERVER_ERROR"].concat((c.p.client_error_codes || []).slice().sort((a) => (a === "CLIENT_FEED_INIT_FAILED" ? -1 : 1)));
    const rows = c.rows("errors_age.csv");
    const grid = h("div", { class: "grid2" }); box.append(grid);
    const xs = []; for (let k = 0; k <= top; k++) xs.push(k);
    codes.forEach((code) => {
      const m = new Map(pool(rows.filter((r) => r.code === code), ["age_bin"], ["n"]).map((r) => [r.age_bin, r.n]));
      const v = xs.map((k) => m.get(k) || 0), total = v.reduce((a, b) => a + b, 0);
      const cell = h("div", {}, h("p", { class: "small-title" }, code + " (" + total + ")")); const sub = h("div", { class: "chart sub" }); cell.append(sub); grid.append(cell);
      barPlot(sub, { labels: xs.map((k) => (k % 5 === 0 ? (k * bin) + (k === top ? "+" : "") : "")), height: 140, margin: { l: 40, t: 6 }, gap: 0.1, minLabelPx: 1,
        series: [{ name: code, color: "--c1", values: v }],
        tip: (i) => "<b>" + (xs[i] * bin) + (xs[i] === top ? " min or more" : " to " + ((xs[i] + 1) * bin) + " min") + "</b><br>" + v[i] + " events" });
    });
    box.append(h("p", { class: "how" }, "x axis: minutes since session creation."));
  },
};

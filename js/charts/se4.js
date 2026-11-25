/* B-errors 4. Status mix with and without server errors. */
import { barPlot } from "../plots.js";
import { pool } from "../select.js";
import { STATUS, STATUS_LABEL } from "../colors.js";
import { legend } from "../svg.js";
import { css, pct0 } from "../util.js";

const STATUSES = ["done", "cancelled", "incomplete"];

export default {
  id: "se4", group: "Server-side errors", title: "Status mix with and without server errors", files: ["status_detail.csv"], window: "created",
  caption: () => "x: participants with at least one SERVER_ERROR and participants with none. y: number of participants, stacked by status at the last pull (done, cancelled, incomplete), created inside the window and for the countries selected above. Participants possibly in session are left out because their status is not final; their number is printed below.",
  how: "Shows whether server errors are linked to people dropping out.",
  draw(box, c) {
    const rows = pool(c.rows("status_detail.csv"), ["has_server_error", "status", "reason"], ["n"]);
    const inSession = rows.filter((r) => r.reason === "in_session").reduce((a, r) => a + r.n, 0);
    const keep = rows.filter((r) => r.reason !== "in_session");
    const groups = [[1, "with a server error"], [0, "without"]];
    const val = (g, s) => keep.filter((r) => r.has_server_error === g && r.status === s).reduce((a, r) => a + r.n, 0);
    const totals = groups.map(([g]) => STATUSES.reduce((a, s) => a + val(g, s), 0));
    barPlot(box, { labels: groups.map((g) => g[1]), height: 240, ylabel: "Participants", gap: 0.5, margin: { l: 48 },
      series: STATUSES.map((s) => ({ name: STATUS_LABEL[s], color: STATUS[s], values: groups.map(([g]) => val(g, s)) })),
      topLabel: (i, t) => t + " participants",
      tip: (i) => "<b>" + groups[i][1] + "</b>" + STATUSES.map((s) => "<br>" + s + ": " + val(groups[i][0], s) + " (" + pct0(val(groups[i][0], s), totals[i]) + ")").join("") });
    const x = document.createElement("div"); x.className = "extra";
    x.innerHTML = legend(STATUSES.map((s) => ({ label: STATUS_LABEL[s], color: css(STATUS[s]) }))) +
      '<p class="how">' + groups.map(([g, l], i) => l + ": " + STATUSES.map((s) => s + " " + pct0(val(g, s), totals[i])).join(", ")).join(". ") + ". " + inSession + " participants possibly in session are left out.</p>";
    box.append(x);
  },
};

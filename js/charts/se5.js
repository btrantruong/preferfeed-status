/* C5. Client-side network failures over time. */
import { linePlot } from "../plots.js";
import { grid, series, sum } from "./_events.js";
import { legend } from "../svg.js";
import { css } from "../util.js";

export default {
  id: "se5", group: "Server-side errors", title: "Client-side network failures over time", files: ["errors_time.csv"], window: "event",
  caption: (m) => "x: server time of the logged error in bins of " + (m.event_bin_minutes || 5) + " minutes, inside the window (the axis of the server-error page). y: events per bin of CLIENT_TRACKING_SEND_FAILED (split into HTTP status codes, for example HTTP 502, and other), CLIENT_FEED_INIT_FAILED and CLIENT_FEED_BATCH_LOAD_FAILED, for the countries selected above; the light gray line is SERVER_ERROR of the same countries for comparison.",
  how: "A 502 seen by the client is a server or proxy failure that may never appear in SERVER_ERROR.",
  draw(box, c) {
    const g = grid(c);
    const rows = c.rows("errors_time.csv");
    const srv = c.p.server_error_code || "SERVER_ERROR";
    const T = "CLIENT_TRACKING_SEND_FAILED", I = "CLIENT_FEED_INIT_FAILED", B = "CLIENT_FEED_BATCH_LOAD_FAILED";
    const ser = [
      { name: "SERVER_ERROR (reference)", color: "--text-muted", opacity: 0.45, width: 1.5, values: series(rows, g, (r) => r.code === srv) },
      { name: "tracking send failed, HTTP status", color: "--c6", values: series(rows, g, (r) => r.code === T && /^HTTP \d{3}$/.test(r.detail)) },
      { name: "tracking send failed, other", color: "--c6", dash: "4 3", values: series(rows, g, (r) => r.code === T && !/^HTTP \d{3}$/.test(r.detail)) },
      { name: "feed init failed", color: "--c7", values: series(rows, g, (r) => r.code === I) },
      { name: "feed batch load failed", color: "--c8", values: series(rows, g, (r) => r.code === B) },
    ];
    linePlot(box, { t0: g.t0, binMs: g.binMs, nBins: g.nBins, series: ser, height: 220, ylabel: "Events", ariaLabel: "Client network failures over time",
      fmtT: (ms) => c.fm.fmt(ms, c.fm.sameDay(c.t0, c.t1) ? { hour: "2-digit", minute: "2-digit" } : { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }), tipTitle: (t) => c.fm.fmtDayHM(t) });
    const x = document.createElement("div"); x.className = "extra";
    x.innerHTML = legend(ser.map((s) => ({ label: s.name + " (" + sum(s.values) + ")", color: css(s.color), faint: s.opacity < 1 })));
    const http = [...new Set(rows.filter((r) => r.code === T && /^HTTP \d{3}$/.test(r.detail)).map((r) => r.detail))];
    if (http.length) x.insertAdjacentHTML("beforeend", '<p class="how">HTTP statuses seen: ' + http.sort().join(", ") + ".</p>");
    box.append(x);
  },
};

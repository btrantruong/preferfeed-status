/* B-errors 1. Server errors over time, one line per country. */
import { linePlot } from "../plots.js";
import { grid, series, sum } from "./_events.js";
import { COUNTRY_SLOTS } from "../colors.js";
import { legend } from "../svg.js";
import { css } from "../util.js";

export default {
  id: "se1", group: "Server-side errors", title: "Server errors over time", files: ["errors_time.csv"], window: "event",
  caption: (m) => "x: server time of the logged error (timestamp_server) in bins of " + (m.event_bin_minutes || 5) + " minutes, inside the window. y: number of SERVER_ERROR events per bin, one line per country (the country selected above alone keeps its color). Only errors of participants created since the launch are counted. The app logs SERVER_ERROR only when the request has a session, and cannot log it when the database write itself fails.",
  how: "Bursts that line up across countries point to shared infrastructure, such as the algorithm server. Bursts on one country only point to that server.",
  draw(box, c) {
    const g = grid(c), code = c.p.server_error_code || "SERVER_ERROR";
    const rows = c.windowRows("errors_time.csv").filter((r) => r.code === code);
    const list = c.state.country === "All" ? c.countries : [c.state.country];
    const ser = list.map((cc) => {
      const v = series(rows, g, (r) => r.country === cc);
      return { name: cc, color: COUNTRY_SLOTS[c.countries.indexOf(cc) % 4], values: v };
    });
    linePlot(box, { t0: g.t0, binMs: g.binMs, nBins: g.nBins, series: ser, height: 220, ylabel: "SERVER_ERROR events", fmtT: (ms) => c.fm.fmt(ms, c.fm.sameDay(c.t0, c.t1) ? { hour: "2-digit", minute: "2-digit" } : { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }),
      tipTitle: (t) => c.fm.fmtDayHM(t), ariaLabel: "Server errors over time" });
    const x = document.createElement("div"); x.className = "extra";
    x.innerHTML = legend(ser.map((s) => ({ label: s.name + " (" + sum(s.values) + " events)", color: css(s.color) })));
    box.append(x);
  },
};

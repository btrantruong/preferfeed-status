/* C1. Algorithm calls over time next to the number of active participants. */
import { frame, linear, yTicks, yAxis, baseline, timeAxis, el, tooltip, local, legend, text } from "../svg.js";
import { grid, series, sum } from "./_events.js";
import { css, h } from "../util.js";

export default {
  id: "ap1", title: "Algorithm calls over time", files: ["algo_calls.csv"], window: "event",
  caption: (m) => "Both plots share the time axis (server time in bins of " + (m.event_bin_minutes || 5) + " minutes inside the window, countries as selected above). Top: algo_exchange rows per bin, init and next_batch as two lines. Bottom: active participants per bin, the distinct participants with at least one record_entry row in the bin. Tracking rows are written by the app server and do not depend on the algorithm server.",
  how: "Calls dropping while active participants stay means the algorithm server stalled.",
  draw(box, c) {
    const g = grid(c), rows = c.rows("algo_calls.csv");
    const init = series(rows, g, (r) => r.endpoint === "init"), nb = series(rows, g, (r) => r.endpoint === "next_batch");
    const act = c.has("active.csv") ? series(c.rows("active.csv"), g, null, "n_active") : null;
    // active participants of several countries add up (a participant belongs to one country)
    const t1 = g.t0 + g.nBins * g.binMs;
    box.replaceChildren();
    const drawLines = (F, vals, names, colors, title, xAxis) => {
      const maxV = Math.max(0, ...vals.flat()), tk = yTicks(maxV, 4), y = linear(0, tk.max, F.m.t + F.ih, F.m.t), xs = linear(g.t0, t1, F.m.l, F.m.l + F.iw);
      yAxis(F, y, tk, null, { label: title });
      vals.forEach((v, j) => el("path", { d: v.map((val, k) => (k ? "L" : "M") + xs(g.t0 + (k + 0.5) * g.binMs).toFixed(1) + "," + y(val).toFixed(1)).join(""), fill: "none", stroke: css(colors[j]), "stroke-width": 2, "stroke-linejoin": "round" }, F.svg));
      baseline(F);
      if (xAxis) timeAxis(F, xs, g.t0, t1, (ms) => c.fm.fmt(ms, c.fm.sameDay(c.t0, c.t1) ? { hour: "2-digit", minute: "2-digit" } : { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }), 90);
      return { xs, y };
    };
    const subTop = h("div", { class: "chart sub" }), subBot = h("div", { class: "chart sub" });
    box.append(subTop, subBot);
    const F1 = frame(subTop, { height: 170, margin: { l: 52, t: 8, b: 8 }, label: "Algorithm calls over time" });
    drawLines(F1, [init, nb], ["init", "next_batch"], ["--c2", "--c1"], "Calls per bin", false);
    const F2 = frame(subBot, { height: 150, margin: { l: 52, t: 8, b: 28 }, label: "Active participants over time" });
    if (act) drawLines(F2, [act], ["active"], ["--text-secondary"], "Active participants", true);
    else { F2.svg.remove(); subBot.append(h("div", { class: "empty" }, "Active participants are not in this pull (they need the full detail pull).")); }
    // shared crosshair on both plots
    const tip = tooltip(box), xs = linear(g.t0, t1, F1.m.l, F1.m.l + F1.iw);
    [F1, act ? F2 : null].filter(Boolean).forEach((F) => {
      const hit = el("rect", { x: F.m.l, y: F.m.t, width: F.iw, height: F.ih, fill: "transparent" }, F.svg);
      const move = (ev) => {
        const p = local(F, ev), k = Math.max(0, Math.min(g.nBins - 1, Math.floor(((p.x - F.m.l) / F.iw) * g.nBins)));
        tip.show("<b>" + c.fm.fmtDayHM(g.t0 + k * g.binMs) + "</b><br>init: " + init[k] + "<br>next_batch: " + nb[k] + (act ? "<br>active participants: " + act[k] : ""), p.sx, p.sy + (F === F2 ? 170 : 0));
      };
      hit.addEventListener("pointermove", move); hit.addEventListener("pointerdown", move); hit.addEventListener("pointerleave", () => tip.hide());
    });
    const x = h("div", { class: "extra" }); x.innerHTML = legend([{ label: "init (" + sum(init) + ")", color: css("--c2") }, { label: "next_batch (" + sum(nb) + ")", color: css("--c1") }].concat(act ? [{ label: "active participants (peak " + Math.max(0, ...act) + ")", color: css("--text-secondary") }] : []));
    box.append(x);
  },
};

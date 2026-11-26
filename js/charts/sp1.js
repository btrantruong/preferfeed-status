/* E2. User spot check: u_long over time (panel E). */
import { frame, linear, yTicks, yAxis, baseline, el, text, tooltip, local, legend } from "../svg.js";
import { DIMS, DIM_VARS } from "../colors.js";
import { pickUser } from "./_spot.js";
import { css, h } from "../util.js";

export default {
  id: "sp1", title: "u_long over time", files: [], window: "created",
  caption: () => "x: minutes since the first exchange of the participant's final attempt; one point per init or next_batch response, marked by small ticks. y: the five components of u_long (us_v_them, fear, outrage, pride, hope; mean-centered scores, so the unit is the score deviation from the inventory mean) as logged with the response. The thin line is 0; the vertical line marks the last exchange in phase warmup. It shows one participant, identified by database id.",
  how: "u_long is the long-term profile after the signals of the previous batch; it is 0 until the first update, and stays 0 for the random condition.",
  draw(box, c) {
    box.replaceChildren();
    const u = pickUser(box, c); if (!u) return;
    const sub = h("div", { class: "chart sub" }); box.append(sub);
    const ex = u.exchanges.filter((e) => e.u_long);
    const F = frame(sub, { height: 260, margin: { l: 48, t: 12, b: 34 }, label: "u_long over time" });
    const all = ex.flatMap((e) => e.u_long.filter((v) => v != null));
    const lo = Math.min(0, ...all), hi = Math.max(0.5, ...all), pad = (hi - lo) * 0.08;
    const y = linear(lo - pad, hi + pad, F.m.t + F.ih, F.m.t);
    const tmax = Math.max(1, ...u.exchanges.map((e) => e.t_min)), x = linear(0, tmax, F.m.l, F.m.l + F.iw);
    const ticks = yTicks(Math.max(Math.abs(lo), Math.abs(hi)), 4);
    [-ticks.max, ...ticks.ticks.map((v) => -v), ...ticks.ticks].filter((v, i, a) => a.indexOf(v) === i && v >= lo - pad && v <= hi + pad).forEach((v) => {
      el("line", { x1: F.m.l, x2: F.m.l + F.iw, y1: y(v), y2: y(v), stroke: css("--grid") }, F.svg); text(F.svg, F.m.l - 6, y(v) + 4, v, { "text-anchor": "end" });
    });
    el("line", { x1: F.m.l, x2: F.m.l + F.iw, y1: y(0), y2: y(0), stroke: css("--border"), "stroke-width": 1.2 }, F.svg);
    const wu = u.exchanges.filter((e) => e.phase === "warmup"); const lastWarm = wu.length ? wu[wu.length - 1].t_min : null;
    if (lastWarm != null) { el("line", { x1: x(lastWarm), x2: x(lastWarm), y1: F.m.t, y2: F.m.t + F.ih, stroke: css("--border") }, F.svg); text(F.svg, x(lastWarm) + 4, F.m.t + 10, "last warm-up request", { class: "t-sec", style: "font-size:11px" }); }
    DIMS.forEach((d, j) => {
      const path = ex.map((e, k) => (k ? "L" : "M") + x(e.t_min).toFixed(1) + "," + y(e.u_long[j] || 0).toFixed(1)).join("");
      el("path", { d: path, fill: "none", stroke: css(DIM_VARS[j]), "stroke-width": 1.8, "stroke-linejoin": "round" }, F.svg);
      const last = ex[ex.length - 1]; if (last) el("circle", { cx: x(last.t_min), cy: y(last.u_long[j] || 0), r: 3.5, fill: css(DIM_VARS[j]), stroke: css("--surface-1"), "stroke-width": 1.5 }, F.svg);
    });
    u.exchanges.forEach((e) => el("line", { x1: x(e.t_min), x2: x(e.t_min), y1: F.m.t + F.ih - 5, y2: F.m.t + F.ih, stroke: css("--text-muted") }, F.svg));
    baseline(F);
    [0, 1, 2, 3, 4, 5].map((k) => (k * tmax) / 5).forEach((t) => text(F.svg, x(t), F.H - 16, t.toFixed(t < 10 ? 1 : 0), { "text-anchor": "middle" }));
    text(F.svg, F.m.l + F.iw / 2, F.H - 3, "minutes since the first exchange (ticks: one per response)", { "text-anchor": "middle" });
    const tip = tooltip(sub), hit = el("rect", { x: F.m.l, y: F.m.t, width: F.iw, height: F.ih, fill: "transparent" }, F.svg);
    const move = (ev) => {
      const p = local(F, ev), t = x.invert(p.x); let best = u.exchanges[0];
      u.exchanges.forEach((e) => { if (Math.abs(e.t_min - t) < Math.abs(best.t_min - t)) best = e; });
      tip.show("<b>" + best.endpoint + " " + (best.request_index == null ? "" : best.request_index) + "</b> at " + best.t_min.toFixed(1) + " min<br>" + DIMS.map((d, j) => d + ": " + (best.u_long ? (best.u_long[j] == null ? "-" : best.u_long[j].toFixed(2)) : "-")).join("<br>"), p.sx, p.sy);
    };
    hit.addEventListener("pointermove", move); hit.addEventListener("pointerdown", move); hit.addEventListener("pointerleave", () => tip.hide());
    const x2 = h("div", { class: "extra" }); x2.innerHTML = legend(DIMS.map((d, j) => ({ label: d, color: css(DIM_VARS[j]) }))); box.append(x2);
  },
};

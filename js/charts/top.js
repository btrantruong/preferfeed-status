/* Top panel: cumulative number of participants by session start inside the window. */
import { css, esc } from "../util.js";
import { frame, el, text, linear, yTicks, yAxis, baseline, tooltip, local, timeAxis } from "../svg.js";
import { pool } from "../select.js";

export default {
  id: "top", title: "Participants since launch", files: ["status_bins.csv"], window: "created",
  caption(meta, c) {
    return "Cumulative number of participants by session start time, " + c.fm.fmtDayHM(c.t0) + " to " + c.fm.fmtDayHM(c.t1) + ".";
  },
  draw(box, c) {
    const nb = c.w.to - c.w.from;
    const per = new Array(Math.max(0, nb)).fill(0);
    pool(c.rows("status_bins.csv"), ["idx"], ["n"]).forEach((r) => { per[r.idx - c.w.from] += r.n; });
    const cum = [0]; per.forEach((n) => cum.push(cum[cum.length - 1] + n));
    const total = cum[cum.length - 1];
    if (total === 0) {
      const none = c.state.country !== "All" && !(c.windowRows("status_bins.csv").some((r) => r.country === c.state.country));
      frame(box, { height: 60 }); box.querySelector("svg").remove();
      const d = document.createElement("div"); d.className = "empty";
      d.textContent = none ? "No participants yet for " + c.state.country + "." : "No participants in this time range.";
      box.prepend(d); return;
    }
    const F = frame(box, { height: 220, margin: { l: 40 }, label: "Cumulative participants over time" });
    const ya = yTicks(total, 5), y = linear(0, ya.max, F.m.t + F.ih, F.m.t);
    const x = (k) => F.m.l + (nb ? (k / nb) * F.iw : 0);
    yAxis(F, y, ya);
    const multiDay = !c.fm.sameDay(c.t0, c.t1);
    timeAxis(F, linear(c.t0, c.t1, F.m.l, F.m.l + F.iw), c.t0, c.t1,
      (ms) => (multiDay ? c.fm.fmt(ms, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : c.fm.fmtHM(ms)), multiDay ? 130 : 90);
    baseline(F);
    const d = cum.map((v, k) => (k ? "L" : "M") + x(k).toFixed(1) + "," + y(v).toFixed(1)).join("");
    el("path", { d, fill: "none", stroke: css("--accent"), "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, F.svg);
    const endDot = el("circle", { cx: x(nb), cy: y(total), r: 4, fill: css("--accent"), stroke: css("--surface-1"), "stroke-width": 2 }, F.svg);
    text(F.svg, Math.min(x(nb), F.m.l + F.iw) - 8, y(total) - 8, total, { "text-anchor": "end", class: "t-ink", style: "font-weight:600" });
    const guide = el("line", { y1: F.m.t, y2: F.m.t + F.ih, stroke: css("--text-muted"), "stroke-dasharray": "3 3", visibility: "hidden" }, F.svg);
    const dot = el("circle", { r: 5, fill: css("--accent"), stroke: css("--surface-1"), "stroke-width": 2, visibility: "hidden" }, F.svg);
    const hit = el("rect", { x: F.m.l, y: F.m.t, width: F.iw, height: F.ih, fill: "transparent" }, F.svg);
    const tip = tooltip(box);
    function move(ev) {
      const p = local(F, ev);
      const k = Math.max(0, Math.min(nb, Math.round(((p.x - F.m.l) / F.iw) * nb)));
      guide.setAttribute("x1", x(k)); guide.setAttribute("x2", x(k)); guide.setAttribute("visibility", "visible");
      dot.setAttribute("cx", x(k)); dot.setAttribute("cy", y(cum[k])); dot.setAttribute("visibility", "visible");
      endDot.setAttribute("visibility", k === nb ? "hidden" : "visible");
      const ms = c.t0 + k * c.binMs;
      tip.show("<b>" + cum[k] + "</b> participants by " + esc(c.fm.fmtHM(ms)) +
        (k ? '<br><span class="muted">+' + per[k - 1] + " from " + esc(c.fm.fmtHM(ms - c.binMs)) + " to " + esc(c.fm.fmtHM(ms)) + "</span>" : ""), p.sx, p.sy);
    }
    hit.addEventListener("pointermove", move); hit.addEventListener("pointerdown", move);
    hit.addEventListener("pointerleave", () => { guide.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); endDot.setAttribute("visibility", "visible"); tip.hide(); });
  },
};

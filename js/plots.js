/* Generic plots built on svg.js: bars (single or stacked) over labelled slots, and lines over a regular time grid. */
import { css } from "./util.js";
import { frame, linear, band, yTicks, yAxis, baseline, text, el, thin, timeAxis, tooltip, local } from "./svg.js";

/** Bars. o: {labels, series:[{name,color(css var),values}], stacked, height, margin, ticks, ylabel, fmtY,
    colorOf(seriesIndex, i) -> css var, topLabel(i, total), tip(i), faint(i), ref(x in slot units), minLabelPx, ariaLabel}. */
export function barPlot(box, o) {
  const F = frame(box, { height: o.height || 190, margin: o.margin, label: o.ariaLabel || "bar chart" });
  const n = o.labels.length;
  const sum = (i) => o.series.reduce((a, s) => a + s.values[i], 0);
  const top = (i) => (o.stacked === false ? Math.max(...o.series.map((s) => s.values[i])) : sum(i));
  const totals = o.labels.map((_, i) => top(i));
  const maxV = Math.max(0, ...totals);
  const ticks = o.ticks || yTicks(maxV * (o.topLabel ? 1.12 : 1), 4);
  const y = linear(0, ticks.max, F.m.t + F.ih, F.m.t);
  const x = band(n, F.m.l, F.m.l + F.iw, o.gap == null ? 0.2 : o.gap);
  yAxis(F, y, ticks, o.fmtY, { label: o.ylabel });
  const group = o.stacked === false ? o.series.length : 1;
  const hits = [];
  o.labels.forEach((_, i) => {
    let acc = 0;
    o.series.forEach((s, j) => {
      const v = s.values[i];
      if (!(v > 0)) { return; }
      const bw = x.bw / group, x0 = x(i) + (o.stacked === false ? j * bw : 0);
      const top = o.stacked === false ? v : acc + v, bottom = o.stacked === false ? 0 : acc;
      const r = el("rect", { x: x0, y: y(top), width: bw, height: Math.max(0, y(bottom) - y(top)), fill: css(o.colorOf ? o.colorOf(j, i) : s.color),
        opacity: o.faint && o.faint(i) ? 0.4 : (s.opacity == null ? 1 : s.opacity) }, F.svg);
      if (o.stacked !== false) acc += v;
    });
    if (o.topLabel) {
      const t = o.topLabel(i, totals[i]);
      if (t) text(F.svg, x(i) + x.bw / 2, y(totals[i]) - 4, t, { "text-anchor": "middle", class: "t-sec" });
    }
    hits.push(el("rect", { x: x(i) - (x.step - x.bw) / 2, y: F.m.t, width: x.step, height: F.ih, fill: "transparent" }, F.svg));
  });
  baseline(F);
  if (o.ref != null) {
    const rx = F.m.l + (o.ref + 0.5) * x.step;  // slot i is centred at (i + 0.5) steps; ref is in slot units
    el("line", { x1: rx, x2: rx, y1: F.m.t, y2: F.m.t + F.ih, stroke: css("--text-muted"), "stroke-dasharray": "3 3" }, F.svg);
  }
  thin(n, F.iw, o.minLabelPx || 40).forEach((i) => text(F.svg, x(i) + x.bw / 2, F.H - F.m.b + 16, o.labels[i], { "text-anchor": "middle" }));
  if (o.tip) {
    const tip = tooltip(box);
    hits.forEach((r, i) => {
      const show = () => tip.show(o.tip(i), ((x(i) + x.bw / 2) / F.W) * F.svg.getBoundingClientRect().width, F.m.t);
      r.addEventListener("pointerenter", show); r.addEventListener("pointerdown", show);
      r.addEventListener("pointerleave", () => tip.hide());
    });
  }
  return { F, x, y };
}

/** Lines over a regular grid of bins. o: {t0, binMs, nBins, series:[{name,color,values,dash,opacity,width}],
    height, margin, fmtT, tipTitle(t), ylabel, ticks, xAxis(true), shared F (to draw on an existing frame)}. */
export function linePlot(box, o) {
  const F = o.F || frame(box, { height: o.height || 190, margin: o.margin, label: o.ariaLabel || "line chart" });
  const t1 = o.t0 + o.nBins * o.binMs;
  const maxV = Math.max(0, ...o.series.flatMap((s) => s.values));
  const ticks = o.ticks || yTicks(maxV, 4);
  const y = linear(0, ticks.max, F.m.t + F.ih, F.m.t);
  const xs = linear(o.t0, t1, F.m.l, F.m.l + F.iw);
  yAxis(F, y, ticks, o.fmtY, { label: o.ylabel });
  o.series.forEach((s) => {
    const d = s.values.map((v, k) => (k ? "L" : "M") + xs(o.t0 + (k + 0.5) * o.binMs).toFixed(1) + "," + y(v).toFixed(1)).join("");
    el("path", { d, fill: "none", stroke: css(s.color), "stroke-width": s.width || 2, "stroke-linejoin": "round", "stroke-linecap": "round",
      "stroke-dasharray": s.dash || "none", opacity: s.opacity == null ? 1 : s.opacity }, F.svg);
  });
  baseline(F);
  if (o.xAxis !== false) timeAxis(F, xs, o.t0, t1, o.fmtT, o.tickPx || 120);
  const guide = el("line", { y1: F.m.t, y2: F.m.t + F.ih, stroke: css("--text-muted"), "stroke-dasharray": "3 3", visibility: "hidden" }, F.svg);
  const hit = el("rect", { x: F.m.l, y: F.m.t, width: F.iw, height: F.ih, fill: "transparent" }, F.svg);
  const tip = tooltip(box);
  const move = (ev) => {
    const p = local(F, ev);
    const k = Math.max(0, Math.min(o.nBins - 1, Math.floor(((p.x - F.m.l) / F.iw) * o.nBins)));
    const gx = xs(o.t0 + (k + 0.5) * o.binMs);
    guide.setAttribute("x1", gx); guide.setAttribute("x2", gx); guide.setAttribute("visibility", "visible");
    tip.show("<b>" + o.tipTitle(o.t0 + k * o.binMs) + "</b>" + o.series.map((s) => '<br><span class="muted">' + s.name + ":</span> " + s.values[k]).join(""), p.sx, p.sy);
  };
  hit.addEventListener("pointermove", move); hit.addEventListener("pointerdown", move);
  hit.addEventListener("pointerleave", () => { guide.setAttribute("visibility", "hidden"); tip.hide(); });
  return { F, xs, y };
}

/* SVG helpers: scales, ticks (pure, tested with node --test) and drawing primitives (need a DOM). */
import { SVGNS, css, esc } from "./util.js";

// ---- pure ---------------------------------------------------------------------------------------------
export function linear(d0, d1, r0, r1) {
  const f = (v) => (d1 === d0 ? r0 : r0 + ((v - d0) / (d1 - d0)) * (r1 - r0));
  f.invert = (p) => (r1 === r0 ? d0 : d0 + ((p - r0) / (r1 - r0)) * (d1 - d0));
  return f;
}

/** Band scale: n slots between r0 and r1 with a gap fraction; f(i) is the start of slot i, f.bw its width. */
export function band(n, r0, r1, gap) {
  const step = n ? (r1 - r0) / n : 0, bw = step * (1 - (gap == null ? 0.25 : gap));
  const f = (i) => r0 + i * step + (step - bw) / 2;
  f.bw = bw; f.step = step;
  return f;
}

/** Integer-friendly y ticks: at most maxTicks steps of 1, 2 or 5 x 10^k covering maxV. */
export function yTicks(maxV, maxTicks) {
  maxTicks = maxTicks || 4;
  const top = Math.max(1, maxV);
  for (let p = 1; ; p *= 10) {
    for (const s of [1, 2, 5]) {
      const step = s * p;
      if (Math.ceil(top / step) <= maxTicks) {
        const max = Math.max(step, Math.ceil(top / step) * step);
        const ticks = []; for (let v = 0; v <= max; v += step) ticks.push(v);
        return { step, max, ticks };
      }
    }
  }
}

/** Nice percentage ticks up to 100. */
export function pctTicks() { return { step: 50, max: 100, ticks: [0, 50, 100] }; }

/** Label thinning: indices to label so that labels are at least minPx apart. */
export function thin(n, widthPx, minPx) {
  const every = Math.max(1, Math.ceil(n / Math.max(1, Math.floor(widthPx / minPx))));
  const out = []; for (let i = 0; i < n; i += every) out.push(i);
  return out;
}

// ---- drawing ------------------------------------------------------------------------------------------
export function el(tag, attrs, parent) {
  const node = document.createElementNS(SVGNS, tag);
  for (const k in attrs || {}) node.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(node);
  return node;
}

export function text(parent, x, y, str, attrs) {
  const t = el("text", Object.assign({ x, y }, attrs || {}), parent);
  t.textContent = str;
  return t;
}

/** Clear a chart box (keeps the tooltip) and add an svg of the box width. Returns the frame. */
export function frame(box, o) {
  [...box.querySelectorAll("svg, .empty, .extra")].forEach((n) => n.remove());
  const W = Math.max(280, box.clientWidth || 600), H = o.height;
  const m = Object.assign({ l: 44, r: 14, t: 10, b: 28 }, o.margin || {});
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": o.label || "chart" });
  box.insertBefore(svg, box.firstChild);
  return { svg, W, H, m, iw: W - m.l - m.r, ih: H - m.t - m.b, box };
}

export function emptyNote(box, msg) {
  [...box.querySelectorAll("svg, .empty, .extra, .sub")].forEach((n) => n.remove());
  const d = document.createElement("div"); d.className = "empty"; d.textContent = msg;
  box.appendChild(d);
}

export function yAxis(F, y, ticks, fmt, o) {
  o = o || {};
  ticks.ticks.forEach((v) => {
    el("line", { x1: F.m.l, x2: F.m.l + F.iw, y1: y(v), y2: y(v), stroke: css("--grid"), "stroke-width": 1 }, F.svg);
    text(F.svg, F.m.l - 6, y(v) + 4, fmt ? fmt(v) : v, { "text-anchor": "end" });
  });
  if (o.label) {
    text(F.svg, 12, F.m.t + F.ih / 2, o.label, { "text-anchor": "middle", transform: `rotate(-90 12 ${F.m.t + F.ih / 2})` });
  }
}

export function baseline(F) {
  el("line", { x1: F.m.l, x2: F.m.l + F.iw, y1: F.m.t + F.ih, y2: F.m.t + F.ih, stroke: css("--border") }, F.svg);
}

/** Labels under a band scale (labels[i] for slot i), thinned to fit. */
export function bandLabels(F, x, labels, minPx) {
  thin(labels.length, F.iw, minPx || 46).forEach((i) => {
    text(F.svg, x(i) + x.bw / 2, F.H - F.m.b + 16, labels[i], { "text-anchor": "middle" });
  });
}

/** Time axis labels for [t0, t1] with a formatter fmtT(ms); ticks about every minPx pixels. */
export function timeAxis(F, xs, t0, t1, fmtT, minPx) {
  const n = Math.max(1, Math.floor(F.iw / (minPx || 90)));
  for (let k = 0; k <= n; k++) {
    const ms = t0 + ((t1 - t0) * k) / n;
    el("line", { x1: xs(ms), x2: xs(ms), y1: F.m.t + F.ih, y2: F.m.t + F.ih + 4, stroke: css("--border") }, F.svg);
    text(F.svg, xs(ms), F.H - 8, fmtT(ms), { "text-anchor": k === 0 ? "start" : k === n ? "end" : "middle" });
  }
}

/** Tooltip bound to a chart box. show(html, px, py) uses coordinates inside the box. */
export function tooltip(box) {
  let tip = box.querySelector(".tip");
  if (!tip) { tip = document.createElement("div"); tip.className = "tip"; box.appendChild(tip); }
  return {
    show(html, px, py) {
      tip.innerHTML = html; tip.style.display = "block";
      const w = tip.offsetWidth, hgt = tip.offsetHeight, bw = box.clientWidth;
      tip.style.left = Math.max(0, Math.min(px + 12 + w > bw ? px - 12 - w : px + 12, bw - w)) + "px";
      tip.style.top = Math.max(0, py - hgt - 8) + "px";
    },
    hide() { tip.style.display = "none"; },
  };
}

/** Pointer position inside the box of an svg event. */
export function local(F, ev) {
  const r = F.svg.getBoundingClientRect();
  return { x: ((ev.clientX - r.left) / r.width) * F.W, y: ((ev.clientY - r.top) / r.height) * F.H, sx: ev.clientX - r.left, sy: ev.clientY - r.top };
}

/** Legend row: items [{label, color, dash}] as HTML. */
export function legend(items) {
  return '<div class="legend">' + items.map((i) => '<span><span class="sw" style="background:' + i.color + (i.faint ? ";opacity:.45" : "") + '"></span>' + esc(i.label) + "</span>").join("") + "</div>";
}

/** Hover a set of svg shapes: html(shapeDatum) per shape; works with mouse, touch and keyboard focus. */
export function attachHover(F, shapes, htmlOf) {
  const tip = tooltip(F.box);
  shapes.forEach(({ node, datum, cx, cy }) => {
    const show = () => tip.show(htmlOf(datum), (cx / F.W) * F.svg.getBoundingClientRect().width, (cy / F.H) * F.svg.getBoundingClientRect().height);
    node.addEventListener("pointerenter", show);
    node.addEventListener("pointerdown", show);
    node.addEventListener("pointerleave", () => tip.hide());
    node.setAttribute("tabindex", "0");
    node.addEventListener("focus", show);
    node.addEventListener("blur", () => tip.hide());
  });
}

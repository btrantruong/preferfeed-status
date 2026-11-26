/* E1. User spot check: batch sums and posts (top, with the dwell time of each post) over the u_long profile (bottom),
   one participant. */
import { frame, linear, yTicks, el, text, legend, thin, baseline } from "../svg.js";
import { DIMS } from "../colors.js";
import { pickUser, dwellRadius, postOffset } from "./_spot.js";
import { bindCard } from "../card.js";
import { css, h } from "../util.js";

const R_MIN = 1.6, R_MAX = 7, SPREAD = 0.3, ML = 52;

/** Grid lines and tick labels for a y scale that may include negative values. */
function grid(F, y, lo, hi) {
  const tk = yTicks(hi, 5).ticks.concat(lo < 0 ? yTicks(-lo, 4).ticks.map((v) => -v).filter((v) => v < 0) : []);
  tk.forEach((v) => { el("line", { x1: F.m.l, x2: F.m.l + F.iw, y1: y(v), y2: y(v), stroke: css("--grid") }, F.svg); text(F.svg, F.m.l - 6, y(v) + 4, v, { "text-anchor": "end" }); });
  if (lo < 0) el("line", { x1: F.m.l, x2: F.m.l + F.iw, y1: y(0), y2: y(0), stroke: css("--text-secondary"), "stroke-dasharray": "4 3" }, F.svg);
}

function axisLabel(F, str) {
  text(F.svg, 12, F.m.t + F.ih / 2, str, { "text-anchor": "middle", transform: `rotate(-90 12 ${F.m.t + F.ih / 2})` });
}

const fmtVec = (s) => "[" + s.join(", ") + "]";
const fmtS = (ms) => (ms == null ? "-" : (ms / 1000).toFixed(1) + " s");

export default {
  id: "sp2", title: "Batch sums and posts", files: [], window: "created",
  caption: (meta) => {
    const cap = (meta.params && meta.params.spot_dwell_cap_s) || 30;
    return "Top: x is the batch index of the final attempt, 1-based (batches 1 and 2 come from the init exchange, which serves two batches; a next_batch response is the next number). y is the sum of the five scores of a post (us_v_them, fear, outrage, pride, hope; raw scores 0 to 3, so 0 to 15). Blue line and dot: the mean of that sum over the posts of the batch. Gray points: the individual posts of the batch, spread over the batch column in the order served; the area of a point is proportional to the time the participant spent on the post (dwell time as reported with the next request, capped at " + cap + " s); a hollow point has no dwell yet because no later request reported that batch. Bottom: same x. Black line: the sum of the five components of u_long; purple line: the Euclidean norm of u_long (square root of the sum of squares). Both are taken from the exchange that served the batch, u_long is mean-centered, and the dashed line is 0. The vertical line ends the init and warm-up batches. Posts come from the project's inventory by post_id. It shows what one participant saw, identified by database id.";
  },
  how: "Hover, focus or tap a batch dot to read its posts with their score vectors, dwell times and texts; click keeps the card open, Escape closes it. The same works on the u_long markers. The u_long of an exchange is the profile that chose the batch when its draw is recommend.",
  draw(box, c) {
    box.replaceChildren();
    const u = pickUser(box, c); if (!u) return;
    const posts = c.spot.posts;
    const capMs = ((c.p && c.p.spot_dwell_cap_s) || 30) * 1000;
    const bat = [];
    u.exchanges.forEach((e) => e.batches.forEach((b) => bat.push({ b, e })));
    bat.forEach((q) => { if (q.e.u_long && q.e.u_long_norm == null) q.e.u_long_norm = Math.hypot(...q.e.u_long.map((v) => v || 0)); });   // files written before the norm existed
    const nmax = Math.max(...bat.map((x) => x.b.batch));
    const warm = bat.filter((q) => q.e.endpoint === "init" || q.e.phase === "warmup");
    const warmLine = (F, x) => { if (warm.length) { const wx = x(Math.max(...warm.map((q) => q.b.batch)) + 0.5); el("line", { x1: wx, x2: wx, y1: F.m.t, y2: F.m.t + F.ih, stroke: css("--border") }, F.svg); } };

    // ---- top panel: batch means and posts (dwell as area)
    box.append(h("div", { class: "small-title" }, "Batch sums and posts"));
    const top = h("div", { class: "chart sub" }); box.append(top);
    const FT = frame(top, { height: 250, margin: { l: ML, t: 10, b: 8 }, label: "Sum of scores per batch and per post" });
    const post = bat.flatMap((x) => x.b.post_ids.map((id) => posts[id].sum));
    const hi = yTicks(Math.max(1, ...post), 5).max, yt = linear(-0.3, hi + 0.3, FT.m.t + FT.ih, FT.m.t);
    const xs = linear(0.5, nmax + 0.5, FT.m.l, FT.m.l + FT.iw);
    grid(FT, yt, 0, hi); warmLine(FT, xs);
    bat.forEach((q) => {
      const n = q.b.post_ids.length;
      q.b.post_ids.forEach((id, k) => {
        const dw = q.b.dwell_ms ? q.b.dwell_ms[k] : null, r = dwellRadius(dw, capMs, R_MIN, R_MAX);
        const cx = xs(q.b.batch + postOffset(k, n, SPREAD)), cy = yt(posts[id].sum);
        const pt = r == null
          ? el("circle", { cx, cy, r: 2.4, fill: "none", stroke: css("--text-muted"), "stroke-width": 1, opacity: 0.8 }, FT.svg)
          : el("circle", { cx, cy, r, fill: css("--text-muted"), opacity: 0.5 }, FT.svg);
        const t = el("title", {}, pt); t.textContent = "batch " + q.b.batch + ", post " + (k + 1) + ": sum " + posts[id].sum + ", dwell " + fmtS(dw);
      });
    });
    const line = bat.filter((q) => q.b.mean_sum != null);
    el("path", { d: line.map((q, k) => (k ? "L" : "M") + xs(q.b.batch).toFixed(1) + "," + yt(q.b.mean_sum).toFixed(1)).join(""), fill: "none", stroke: css("--c1"), "stroke-width": 2, "stroke-linejoin": "round" }, FT.svg);
    line.forEach((q) => {
      const dot = el("circle", { cx: xs(q.b.batch), cy: yt(q.b.mean_sum), r: 5, fill: css("--c1"), stroke: css("--surface-1"), "stroke-width": 1.5, style: "cursor:pointer", "aria-label": "Batch " + q.b.batch + ", mean sum " + q.b.mean_sum.toFixed(1) }, FT.svg);
      bindCard(dot, () => ({
        title: "Batch " + q.b.batch + " · mean sum " + q.b.mean_sum.toFixed(1),
        sub: q.e.endpoint + (q.e.request_index != null ? " " + q.e.request_index : "") + " · phase " + (q.e.phase || "-") + " · draw " + (q.e.draw || "-"),
        lines: ["dimensions: " + DIMS.join(", "), q.e.u_long ? "u_long: " + fmtVec(q.e.u_long.map((v) => (v == null ? "-" : v.toFixed(2)))) + ", sum " + q.e.u_long_sum.toFixed(2) + ", norm " + q.e.u_long_norm.toFixed(2) : "u_long: -"],
        posts: q.b.post_ids.map((id, k) => { const p = posts[id]; return { head: (k + 1) + ". " + fmtVec(p.scores) + " sum " + p.sum + " · dwell " + fmtS(q.b.dwell_ms ? q.b.dwell_ms[k] : null) + " · " + p.country + " · " + p.platform, text: p.text + (p.cut ? " [cut]" : "") }; }),
      }));
    });
    baseline(FT); axisLabel(FT, "sum of the 5 scores");

    // ---- bottom panel: u_long sum and norm
    box.append(h("div", { class: "small-title" }, "u_long: sum and norm"));
    const bot = h("div", { class: "chart sub" }); box.append(bot);
    const FB = frame(bot, { height: 200, margin: { l: ML, t: 10, b: 34 }, label: "Sum and norm of u_long per batch" });
    const ul = bat.filter((q) => q.e.u_long_sum != null);
    const vals = ul.flatMap((q) => [q.e.u_long_sum, q.e.u_long_norm]);
    const lo = Math.min(0, ...vals), hb = yTicks(Math.max(1, ...vals), 5).max, yb = linear(lo - 0.3, hb + 0.3, FB.m.t + FB.ih, FB.m.t);
    const xb = linear(0.5, nmax + 0.5, FB.m.l, FB.m.l + FB.iw);
    grid(FB, yb, lo, hb); warmLine(FB, xb);
    const path = (key, color) => el("path", { d: ul.map((q, k) => (k ? "L" : "M") + xb(q.b.batch).toFixed(1) + "," + yb(q.e[key]).toFixed(1)).join(""), fill: "none", stroke: color, "stroke-width": 1.5, "stroke-linejoin": "round" }, FB.svg);
    path("u_long_sum", css("--text-primary")); path("u_long_norm", css("--c7"));
    const card = (q) => () => ({
      title: "Batch " + q.b.batch + " · u_long",
      sub: q.e.endpoint + (q.e.request_index != null ? " " + q.e.request_index : "") + " · phase " + (q.e.phase || "-") + " · draw " + (q.e.draw || "-"),
      lines: ["dimensions: " + DIMS.join(", "), "u_long: " + fmtVec(q.e.u_long.map((v) => (v == null ? "-" : v.toFixed(2)))), "sum " + q.e.u_long_sum.toFixed(2) + ", norm " + q.e.u_long_norm.toFixed(2)],
    });
    ul.forEach((q) => {
      const s = el("rect", { x: xb(q.b.batch) - 3, y: yb(q.e.u_long_sum) - 3, width: 6, height: 6, fill: css("--text-primary"), style: "cursor:pointer", "aria-label": "Batch " + q.b.batch + ", u_long sum " + q.e.u_long_sum.toFixed(2) }, FB.svg);
      bindCard(s, card(q));
    });
    ul.forEach((q) => {
      const d = el("circle", { cx: xb(q.b.batch), cy: yb(q.e.u_long_norm), r: 3.2, fill: css("--c7"), stroke: css("--surface-1"), "stroke-width": 1, style: "cursor:pointer", "aria-label": "Batch " + q.b.batch + ", u_long norm " + q.e.u_long_norm.toFixed(2) }, FB.svg);
      bindCard(d, card(q));
    });
    baseline(FB); axisLabel(FB, "u_long (sum, norm)");
    thin(nmax, FB.iw, 28).forEach((i) => text(FB.svg, xb(i + 1), FB.H - 16, i + 1, { "text-anchor": "middle" }));
    text(FB.svg, FB.m.l + FB.iw / 2, FB.H - 3, "batch index (1-based)", { "text-anchor": "middle" });

    // ---- legend with the size key
    const key = [1, 5, capMs / 1000].filter((v, i, a) => a.indexOf(v) === i).map((s) => {
      const r = dwellRadius(s * 1000, capMs, R_MIN, R_MAX);
      return '<span style="display:inline-flex;align-items:center;gap:4px;white-space:nowrap"><svg width="' + (2 * R_MAX + 2) + '" height="' + (2 * R_MAX + 2) + '"><circle cx="' + (R_MAX + 1) + '" cy="' + (R_MAX + 1) + '" r="' + r.toFixed(1) + '" fill="' + css("--text-muted") + '" opacity="0.5"></circle></svg> ' + s + " s</span>";
    }).join("");
    const lg = h("div", { class: "extra" });
    lg.innerHTML = legend([{ label: "batch mean (hover for the posts)", color: css("--c1") }, { label: "posts (area = dwell time)", color: css("--text-muted"), faint: true }, { label: "u_long sum (dashed line = 0)", color: css("--text-primary") }, { label: "u_long norm", color: css("--c7") }])
      + '<div class="legend"><span>dwell key:</span>' + key + '<span>hollow point: no dwell reported yet</span></div>';
    box.append(lg);
  },
};

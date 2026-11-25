/* D2. User spot check: mean sum of the five scores per served batch, with the posts on hover (local preview only). */
import { frame, linear, yTicks, yAxis, baseline, el, text, legend, thin } from "../svg.js";
import { DIMS } from "../colors.js";
import { pickUser } from "./_spot.js";
import { bindCard } from "../card.js";
import { css, h } from "../util.js";

export default {
  id: "sp2", title: "Batch sums and posts", files: [], window: "created",
  caption: () => "x: batch index of the final attempt, 1-based (batches 1 and 2 come from the init exchange, which serves two batches; a next_batch response is the next number). y: for one batch, the mean over its posts of the sum of the five scores of a post (us_v_them, fear, outrage, pride, hope; raw scores 0 to 3, so a post is 0 to 15; gray dots are the individual posts). Black line: the sum of the five components of u_long logged with the exchange that served the batch (mean-centered, same axis; the dashed line is 0). The vertical line ends the init and warm-up batches. Posts come from the project's inventory by post_id. Local preview only: it shows what one participant saw.",
  how: "Hover, focus or tap a batch dot to read its posts with their score vectors and texts; click keeps the card open, Escape closes it. The u_long of an exchange is the profile that chose the batch when its draw is recommend.",
  draw(box, c) {
    box.replaceChildren();
    const u = pickUser(box, c); if (!u) return;
    const posts = c.spot.posts, inv = (c.spot.inventory || {})[u.country];
    const bat = [];
    u.exchanges.forEach((e) => e.batches.forEach((b) => bat.push({ b, e })));
    const sub = h("div", { class: "chart sub" }); box.append(sub);
    const F = frame(sub, { height: 280, margin: { l: 48, t: 12, b: 34 }, label: "Mean sum of scores per batch" });
    const post = bat.flatMap((x) => x.b.post_ids.map((id) => posts[id].sum));
    const us = bat.map((x) => x.e.u_long_sum).filter((v) => v != null);
    const lo = Math.min(0, ...us, ...post), hi = Math.max(1, ...us, ...post);
    const y = linear(lo - 0.3, hi + 0.5, F.m.t + F.ih, F.m.t);
    const nmax = Math.max(...bat.map((x) => x.b.batch)), x = linear(0.5, nmax + 0.5, F.m.l, F.m.l + F.iw);
    const tk = yTicks(hi, 5).ticks.concat(lo < 0 ? yTicks(-lo, 4).ticks.map((v) => -v).filter((v) => v < 0) : []);
    tk.forEach((v) => { el("line", { x1: F.m.l, x2: F.m.l + F.iw, y1: y(v), y2: y(v), stroke: css("--grid") }, F.svg); text(F.svg, F.m.l - 6, y(v) + 4, v, { "text-anchor": "end" }); });
    el("line", { x1: F.m.l, x2: F.m.l + F.iw, y1: y(0), y2: y(0), stroke: css("--text-secondary"), "stroke-dasharray": "4 3" }, F.svg);
    const warm = bat.filter((q) => q.e.endpoint === "init" || q.e.phase === "warmup");
    if (warm.length) { const wx = x(Math.max(...warm.map((q) => q.b.batch)) + 0.5); el("line", { x1: wx, x2: wx, y1: F.m.t, y2: F.m.t + F.ih, stroke: css("--border") }, F.svg); }
    bat.forEach((q) => q.b.post_ids.forEach((id) => el("circle", { cx: x(q.b.batch), cy: y(posts[id].sum), r: 2.5, fill: css("--text-muted"), opacity: 0.55 }, F.svg)));
    const uline = bat.filter((q) => q.e.u_long_sum != null);
    el("path", { d: uline.map((q, k) => (k ? "L" : "M") + x(q.b.batch).toFixed(1) + "," + y(q.e.u_long_sum).toFixed(1)).join(""), fill: "none", stroke: css("--text-primary"), "stroke-width": 1.4 }, F.svg);
    uline.forEach((q) => el("rect", { x: x(q.b.batch) - 2.5, y: y(q.e.u_long_sum) - 2.5, width: 5, height: 5, fill: css("--text-primary") }, F.svg));
    const line = bat.filter((q) => q.b.mean_sum != null);
    el("path", { d: line.map((q, k) => (k ? "L" : "M") + x(q.b.batch).toFixed(1) + "," + y(q.b.mean_sum).toFixed(1)).join(""), fill: "none", stroke: css("--c1"), "stroke-width": 2, "stroke-linejoin": "round" }, F.svg);
    const fmtVec = (s) => "[" + s.join(", ") + "]";
    line.forEach((q) => {
      const dot = el("circle", { cx: x(q.b.batch), cy: y(q.b.mean_sum), r: 5.5, fill: css("--c1"), stroke: css("--surface-1"), "stroke-width": 1.5, style: "cursor:pointer", "aria-label": "Batch " + q.b.batch + ", mean sum " + q.b.mean_sum.toFixed(1) }, F.svg);
      bindCard(dot, () => ({
        title: "Batch " + q.b.batch + " · mean sum " + q.b.mean_sum.toFixed(1),
        sub: q.e.endpoint + (q.e.request_index != null ? " " + q.e.request_index : "") + " · phase " + (q.e.phase || "-") + " · draw " + (q.e.draw || "-"),
        lines: ["dimensions: " + DIMS.join(", "), q.e.u_long ? "u_long: " + fmtVec(q.e.u_long.map((v) => (v == null ? "-" : v.toFixed(2)))) + ", sum " + q.e.u_long_sum.toFixed(2) : "u_long: -"],
        warn: inv && inv.match === false ? "The inventory file used here differs from the one the server loaded; the scores shown are those of the local file." : null,
        posts: q.b.post_ids.map((id, k) => { const p = posts[id]; return { head: (k + 1) + ". " + fmtVec(p.scores) + " sum " + p.sum + " · " + p.country + " · " + p.platform, text: p.text + (p.cut ? " [cut]" : "") }; }),
      }));
    });
    baseline(F);
    thin(nmax, F.iw, 28).forEach((i) => text(F.svg, x(i + 1), F.H - 16, i + 1, { "text-anchor": "middle" }));
    text(F.svg, F.m.l + F.iw / 2, F.H - 3, "batch index (1-based)", { "text-anchor": "middle" });
    const lg = h("div", { class: "extra" }); lg.innerHTML = legend([{ label: "batch mean (hover for the posts)", color: css("--c1") }, { label: "post sums", color: css("--text-muted"), faint: true }, { label: "sum of u_long (dashed line = 0)", color: css("--text-primary") }]); box.append(lg);
  },
};

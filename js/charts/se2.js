/* B-errors 2. Errors by type and sequence: flow chart of the first FLOW_STEPS error runs. */
import { pool } from "../select.js";
import { frame, el, text, tooltip } from "../svg.js";
import { columns, layout, bands, fitScale, START, END } from "../flow.js";
import { FLOW } from "../colors.js";
import { css, esc, h } from "../util.js";

export default {
  id: "se2", group: "Server-side errors", title: "Errors by type and sequence", files: ["error_flow.csv"], window: "created",
  caption: (m) => "x: position in the participant's error log (error run 1 to " + ((m.params || {}).flow_steps || 4) + "). Nodes: participants whose k-th run is of the given type, height proportional to the number of participants. Bands between adjacent columns: participants who went from one type to the next. A gray node marks participants whose log ended. Errors are ordered by server time, mapped to eight types (the three client failures are grouped) and consecutive repeats are merged. Participants created inside the window, countries as selected above.",
  how: "Followed by is an order in the log, not a cause. A band that carries almost all of a node into the next node says that the second type follows the first in almost all of those participants.",
  draw(box, c) {
    const steps = c.p.flow_steps || 4, order = c.meta.flow_nodes || [];
    const tr = pool(c.rows("error_flow.csv"), ["step", "from_node", "to_node"], ["n"]).map((r) => ({ step: r.step, from: r.from_node, to: r.to_node, n: r.n }));
    const total = tr.filter((t) => t.step === 0).reduce((a, t) => a + t.n, 0);
    if (!total) { box.append(h("div", { class: "empty" }, "No participant with a logged error in this time range.")); return; }
    const cols = columns(tr, steps, order.concat(["other"]));
    const F = frame(box, { height: 330, margin: { l: 8, r: 8, t: 22, b: 8 }, label: "Error types and their sequence" });
    const nodeW = 14, gap = 8, colX = (k) => F.m.l + (steps === 1 ? 0 : (k * (F.iw - nodeW)) / (steps - 1));
    const scale = fitScale(cols, F.ih, gap), lay = layout(cols, scale, gap), bs = bands(tr, lay, scale);
    const tip = tooltip(box);
    const colorOf = (n) => css(FLOW[n] || "--text-muted");
    bs.forEach((b) => {
      const x0 = colX(b.k - 1) + nodeW, x1 = colX(b.k), mid = (x0 + x1) / 2, ya = F.m.t + b.y0, yb = F.m.t + b.y1;
      const d = `M${x0},${ya} C${mid},${ya} ${mid},${yb} ${x1},${yb} L${x1},${yb + b.h} C${mid},${yb + b.h} ${mid},${ya + b.h} ${x0},${ya + b.h} Z`;
      const p = el("path", { d, fill: colorOf(b.from), opacity: 0.35 }, F.svg);
      const show = (ev) => { const r = F.svg.getBoundingClientRect(); tip.show(esc(b.from) + " then " + esc(b.to) + ": <b>" + b.n + "</b> participants", ev.clientX - r.left, ev.clientY - r.top); };
      p.addEventListener("pointermove", show); p.addEventListener("pointerdown", show); p.addEventListener("pointerleave", () => tip.hide());
    });
    for (let k = 0; k < steps; k++) text(F.svg, colX(k) + nodeW / 2, 14, "run " + (k + 1), { "text-anchor": k === 0 ? "start" : k === steps - 1 ? "end" : "middle", class: "t-sec" });
    Object.values(lay.nodes).forEach((n) => {
      const x = colX(n.k), y = F.m.t + n.y;
      const r = el("rect", { x, y, width: nodeW, height: Math.max(n.h, 1), fill: colorOf(n.node), rx: 2 }, F.svg);
      const label = (n.node === END ? "no further error" : n.node) + " " + n.n;
      if (n.h >= 12) {
        const right = n.k < steps / 2;
        text(F.svg, right ? x + nodeW + 4 : x - 4, y + n.h / 2 + 4, label, { "text-anchor": right ? "start" : "end", class: "flowlabel t-ink" });
      }
      const show = (ev) => { const rr = F.svg.getBoundingClientRect(); tip.show("<b>" + esc(n.node === END ? "no further error" : n.node) + "</b>: " + n.n + " participants (run " + (n.k + 1) + ")", ev.clientX - rr.left, ev.clientY - rr.top); };
      r.addEventListener("pointermove", show); r.addEventListener("pointerdown", show); r.addEventListener("pointerleave", () => tip.hide());
    });
    // legend and table view of the same counts
    const used = [...new Set(tr.map((t) => t.to).filter((n) => n !== END))];
    const extra = h("div", { class: "extra" });
    extra.innerHTML = '<div class="legend">' + used.concat([END]).map((n) => '<span><span class="sw" style="background:' + colorOf(n) + '"></span>' + esc(n === END ? "no further error" : n) + "</span>").join("") + "</div>";
    const rows = tr.slice().sort((a, b) => a.step - b.step || b.n - a.n);
    const det = h("details", {}, h("summary", {}, "Table view"));
    det.innerHTML += '<table><thead><tr><th>run</th><th>from</th><th>to</th><th class="num">participants</th></tr></thead><tbody>' +
      rows.map((r) => "<tr><td>" + (r.step + 1) + "</td><td>" + esc(r.from) + "</td><td>" + esc(r.to) + '</td><td class="num">' + r.n + "</td></tr>").join("") + "</tbody></table>";
    extra.append(det); box.append(extra);
  },
};

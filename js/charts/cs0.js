/* A1. Status of these participants at the last pull: share bar and outcome table. */
import { esc, pct, css } from "../util.js";
import { frame, el, text, tooltip } from "../svg.js";
import { pool } from "../select.js";
import { GROUPS, outcomeTree } from "./_outcomes.js";

export default {
  id: "cs0", title: "Status of these participants at the last pull", files: ["outcome_bins.csv"], window: "created",
  caption: (m) => "x: share of the participants created in the window; the bar counts them as done, still in session or left session at the last pull, and the table splits these. Retried: the timeline was started again. Error: a logged code other than " +
    ((m.params || {}).outcome_ignore_codes || []).join(", ") + "; software stops (idle, reload, bot) and technical failures both count. Retried after error: an error was logged before the last restart. Error, no retry: no error came before a restart. Still in session: not done, not stopped and inside the session time (the rule of panel B).",
  how: "The shares add up to 100%. A participant's category can still change after they are counted, for example after a restart.",
  draw(box, c) {
    const tree = outcomeTree(pool(c.rows("outcome_bins.csv"), ["outcome", "last_error"], ["n"]));
    const total = tree.total;
    c.sel = { total };
    if (!total) { frame(box, { height: 10 }); box.querySelector("svg").remove(); box.prepend(Object.assign(document.createElement("div"), { className: "empty", textContent: "No participants in this time range." })); return; }
    const F = frame(box, { height: 34, margin: { l: 0, r: 0, t: 0, b: 0 }, label: "Share of participants by status" });
    const gap = 2;
    const clip = el("clipPath", { id: "barclip" }, el("defs", {}, F.svg));
    el("rect", { x: 0, y: 0, width: F.W, height: 34, rx: 4 }, clip);
    const g = el("g", { "clip-path": "url(#barclip)" }, F.svg);
    const present = GROUPS.filter((s) => tree.groups[s.key] > 0);
    const tip = tooltip(box);
    let x0 = 0;
    present.forEach((s, i) => {
      const n = tree.groups[s.key];
      const w = (n / total) * F.W, wDraw = Math.max(0, w - (i < present.length - 1 ? gap : 0));
      const r = el("rect", { x: x0, y: 0, width: wDraw, height: 34, fill: css(s.color) }, g);
      const label = s.label + " " + pct(n, total);
      const ink = s.key === "left" ? css("--surface-1") : "#0b0b0b";
      if (wDraw > label.length * 7 + 12) text(F.svg, x0 + 8, 21, label, { style: "fill:" + ink + ";font-weight:600;pointer-events:none" });
      const show = (ev) => { const rr = F.svg.getBoundingClientRect(); tip.show("<b>" + esc(s.label) + "</b>: " + n + " (" + pct(n, total) + ")", ev.clientX - rr.left, 34 + 40); };
      r.addEventListener("pointermove", show); r.addEventListener("pointerdown", show); r.addEventListener("pointerleave", () => tip.hide());
      x0 += w;
    });
    const maxShare = Math.max(...tree.table.map((r) => r.n / total));
    const swatch = (color) => (color ? '<span class="sw" style="background:var(' + color + ')"></span>' : "");
    const bar = (r) => (r.color ? '<div class="minibar" style="width:' + ((r.n / total) / (maxShare || 1) * 100).toFixed(1) + "%;background:var(" + r.color + ')"></div>' : "");
    const rowClass = ["group", "sub", "sub2", "sub3"];
    let html = '<div class="legend">' + GROUPS.map((s) => "<span>" + swatch(s.color) + s.label + "</span>").join("") + "</div>";
    html += '<table><thead><tr><th>Status</th><th class="num">n</th><th class="num">share</th><th class="bar-cell"><span class="sr">share bar</span></th></tr></thead><tbody>';
    tree.table.forEach((r) => {
      html += '<tr class="' + rowClass[r.level] + '"><td>' + (r.level === 0 ? swatch(r.color) : "") + esc(r.label) + '</td><td class="num">' + r.n + '</td><td class="num">' + pct(r.n, total) + '</td><td class="bar-cell">' + bar(r) + "</td></tr>";
    });
    html += '<tr class="total"><td>total</td><td class="num">' + total + '</td><td class="num">100%</td><td class="bar-cell"></td></tr></tbody></table>';
    const extra = document.createElement("div"); extra.className = "extra"; extra.innerHTML = html; box.appendChild(extra);
  },
};

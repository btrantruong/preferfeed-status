/* A0. Status of these participants at the last pull: share bar and table (the live page's chart, moved). */
import { esc, pct } from "../util.js";
import { frame, el, text, tooltip } from "../svg.js";
import { css } from "../util.js";
import { STATUS, STATUS_LABEL } from "../colors.js";
import { pool } from "../select.js";

const STATUSES = ["done", "cancelled", "incomplete"];
const LABEL = { done: "done", cancelled: "cancelled", incomplete: "incomplete", bot: "bot", idle: "idle", reload: "reload",
  other: "other", in_session: "possibly in session", error_logged: "error logged", no_error: "no error" };

export default {
  id: "cs0", title: "Status of these participants at the last pull", files: ["status_bins.csv"], window: "created",
  caption: () => "x: share of the participants created in the window; bar segments and table rows count participants by status (and reason) at the last pull, as stored in visited_users (done, cancelled) and the error log (reason).",
  how: "The shares add up to 100%. A participant's status can still change after they are counted, for example after a restart.",
  draw(box, c) {
    const rows = pool(c.rows("status_bins.csv"), ["status", "reason"], ["n"]);
    const total = rows.reduce((a, r) => a + r.n, 0);
    const tot = {}; STATUSES.forEach((s) => { tot[s] = 0; });
    rows.forEach((r) => { tot[r.status] += r.n; });
    const cat = {}; rows.forEach((r) => { cat[r.status + "|" + r.reason] = r.n; });
    c.sel = { total };
    if (!total) { frame(box, { height: 10 }); box.querySelector("svg").remove(); box.prepend(Object.assign(document.createElement("div"), { className: "empty", textContent: "No participants in this time range." })); return; }
    const F = frame(box, { height: 34, margin: { l: 0, r: 0, t: 0, b: 0 }, label: "Share of participants by status" });
    const gap = 2;
    const clip = el("clipPath", { id: "barclip" }, el("defs", {}, F.svg));
    el("rect", { x: 0, y: 0, width: F.W, height: 34, rx: 4 }, clip);
    const g = el("g", { "clip-path": "url(#barclip)" }, F.svg);
    const present = STATUSES.filter((s) => tot[s] > 0);
    const tip = tooltip(box);
    let x0 = 0;
    present.forEach((s, i) => {
      const w = (tot[s] / total) * F.W, wDraw = Math.max(0, w - (i < present.length - 1 ? gap : 0));
      const r = el("rect", { x: x0, y: 0, width: wDraw, height: 34, fill: css(STATUS[s]) }, g);
      const label = LABEL[s] + " " + pct(tot[s], total);
      if (wDraw > label.length * 7 + 12) text(F.svg, x0 + 8, 21, label, { style: "fill:#0b0b0b;font-weight:600;pointer-events:none" });
      const show = (ev) => { const rr = F.svg.getBoundingClientRect(); tip.show("<b>" + esc(LABEL[s]) + "</b>: " + tot[s] + " (" + pct(tot[s], total) + ")", ev.clientX - rr.left, 34 + 40); };
      r.addEventListener("pointermove", show); r.addEventListener("pointerdown", show); r.addEventListener("pointerleave", () => tip.hide());
      x0 += w;
    });
    const reasons = {}; c.meta.categories.forEach((k) => { (reasons[k.status] = reasons[k.status] || []).push(k.reason); });
    const maxShare = Math.max(...STATUSES.map((s) => tot[s] / total));
    const bar = (n, s) => '<div class="minibar" style="width:' + ((n / total) / (maxShare || 1) * 100).toFixed(1) + "%;background:var(" + STATUS[s] + ')"></div>';
    let html = '<div class="legend">' + STATUSES.map((s) => '<span><span class="sw" style="background:var(' + STATUS[s] + ')"></span>' + LABEL[s] + "</span>").join("") + "</div>";
    html += '<table><thead><tr><th>Status</th><th class="num">n</th><th class="num">share</th><th class="bar-cell"><span class="sr">share bar</span></th></tr></thead><tbody>';
    STATUSES.forEach((s) => {
      html += '<tr class="group"><td><span class="sw" style="background:var(' + STATUS[s] + ')"></span>' + LABEL[s] + '</td><td class="num">' + tot[s] + '</td><td class="num">' + pct(tot[s], total) + '</td><td class="bar-cell">' + bar(tot[s], s) + "</td></tr>";
      if (s === "done") return;
      (reasons[s] || []).forEach((r) => {
        const n = cat[s + "|" + r] || 0;
        html += '<tr class="sub"><td>' + esc(LABEL[r] || r) + '</td><td class="num">' + n + '</td><td class="num">' + pct(n, total) + '</td><td class="bar-cell">' + bar(n, s) + "</td></tr>";
      });
    });
    html += '<tr class="total"><td>total</td><td class="num">' + total + '</td><td class="num">100%</td><td class="bar-cell"></td></tr></tbody></table>';
    const extra = document.createElement("div"); extra.className = "extra"; extra.innerHTML = html; box.appendChild(extra);
  },
};

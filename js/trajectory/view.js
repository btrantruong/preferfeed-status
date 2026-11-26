/* The stacked panels of one attempt on a shared batch axis, with the alignment toggle. Used by panel E of the
   status page (charts/sp.js) and by the local view (local.js). Post text is untrusted: textContent only. */
import { el, text, legend } from "../svg.js";
import { DIMS, DIM_VARS } from "../colors.js";
import { dwellRadius, postOffset } from "../charts/_spot.js";
import { bindCard, closeCard } from "../card.js";
import { css, h } from "../util.js";
import { MODES, servedBatch, profileColumns, batchList, maxBatch, warmEnd, signalsOf, available, rewardMean, centeredRange, paddedRange, niceTicks, segments } from "./model.js";

const AXIS_W = 46, PAD = 4, MIN_COL = 24, R_MIN = 1.6, R_MAX = 6, SPREAD = 0.34;
const REWARD = { 1: "--c3", 0: "--text-muted", "-1": "--c8" };
const scrolls = new Map();   // scroll position per participant, kept across redraws

const fmt = (v) => (v == null ? "-" : v.toFixed(2));
const vec = (v) => (v ? "[" + v.map(fmt).join(", ") + "]" : "-");
const sec = (ms) => (ms == null ? "-" : (ms / 1000).toFixed(1) + " s");

function svg(width, height, label) {
  const s = el("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": label });
  s.style.width = width + "px"; s.style.height = height + "px";
  return s;
}

/** o: {attempt, posts, mode, onMode(key), key, capS, alpha, hiddenNote} */
export function renderTrajectory(root, o) {
  closeCard();
  root.replaceChildren();
  const a = o.attempt, have = available(a), hidden = !!o.hiddenNote;
  const mode = have.signalBatch || hidden ? o.mode : "informs";
  const n = maxBatch(a), batches = batchList(a), warm = warmEnd(a), capMs = (o.capS || 30) * 1000;
  const box = h("div", { class: "traj" }); root.append(box);

  // ---- toggle, mode sentence, checks, readout
  if (!hidden) {
    const bar = h("div", { class: "userbar", role: "group", "aria-label": "Alignment of the profile with the batches" }, h("span", {}, "Same column reads as: profile"));
    MODES.forEach((m) => {
      const b = h("button", { type: "button", "aria-pressed": String(m.key === mode) }, m.label + " this batch");
      if (m.key === "informed" && !have.signalBatch) { b.disabled = true; b.title = "The data of this pull has no signal batch"; }
      b.addEventListener("click", () => o.onMode(m.key));
      bar.append(b);
    });
    box.append(bar, h("p", { class: "how" }, MODES.find((m) => m.key === mode).sentence));
  }
  if (a.checks) {
    const c = a.checks, bad = c.u_short[0] < c.u_short[1] || c.u_long[0] < c.u_long[1];
    box.append(h("p", { class: bad ? "cov" : "how" }, "Checks against the log: rebuilt u_short equals the logged one in " + c.u_short[0] + " of " + c.u_short[1] +
      " updating requests; u_long follows the update rule" + (o.alpha ? " with alpha " + o.alpha : "") + " in " + c.u_long[0] + " of " + c.u_long[1] + " requests."));
  }
  const readout = h("div", { class: "trajread", "aria-live": "polite" }, "Move over a panel to read a column; click a blue batch mean for its posts and the request chain.");
  const scroll = h("div", { class: "trajscroll" });
  box.append(readout, scroll);

  const avail = Math.max(280, box.clientWidth || 800) - AXIS_W - 2 * PAD;
  const col = Math.max(MIN_COL, Math.floor(avail / n)), width = n * col + 2 * PAD;
  const X = (b) => PAD + (b - 0.5) * col;
  const guides = [];

  function panel(title, height, range, ticks, tickLabel, draw) {
    const top = 6, bottom = 18, ih = height - top - bottom;
    const Y = (v) => top + ih - ((v - range.lo) / (range.hi - range.lo)) * ih;
    const axis = svg(AXIS_W, height, title + " axis"), plot = svg(width, height, title);
    scroll.append(h("div", { class: "trajtitle small-title" }, title), h("div", { class: "trajrow" }, h("div", { class: "trajaxis" }, axis), plot));
    ticks.forEach((v) => {
      el("line", { x1: 0, x2: width, y1: Y(v), y2: Y(v), stroke: css(v === 0 ? "--border" : "--grid") }, plot);
      text(axis, AXIS_W - 6, Y(v) + 4, tickLabel ? tickLabel(v) : v, { "text-anchor": "end" });
    });
    if (warm != null) el("line", { x1: PAD + warm * col, x2: PAD + warm * col, y1: top, y2: top + ih, stroke: css("--text-muted"), "stroke-dasharray": "2 3" }, plot);
    guides.push(el("line", { y1: top, y2: top + ih, stroke: css("--text-secondary"), "stroke-dasharray": "3 3", visibility: "hidden" }, plot));
    draw(plot, Y);
    const every = Math.max(1, Math.ceil(26 / col));
    for (let b = 1; b <= n; b += every) text(plot, X(b), height - 4, b, { "text-anchor": "middle" });
    plot.addEventListener("pointermove", (ev) => point(plot, ev));
    plot.addEventListener("pointerdown", (ev) => point(plot, ev));
  }

  function point(plot, ev) {
    const r = plot.getBoundingClientRect();
    const b = Math.max(1, Math.min(n, Math.floor((ev.clientX - r.left - PAD) / col) + 1));
    guides.forEach((g) => { g.setAttribute("x1", X(b)); g.setAttribute("x2", X(b)); g.setAttribute("visibility", "visible"); });
    const batch = batches.find((q) => q.batch === b);
    const lines = ["Column " + b + ". Batch " + b + ": mean sum " + (batch ? fmt(batch.b.mean_sum) : "-") + (batch && batch.b.mean_centered ? ", mean per dimension " + vec(batch.b.mean_centered) : "")];
    if (!hidden) {
      const q = profileColumns(a, mode).filter((p) => p.x === b).pop();
      if (!q) lines.push("No reward or profile in this column in this mode.");
      else {
        const e = q.e;
        lines.push("Request with the signals of batch " + (e.signal_batch == null ? "-" : e.signal_batch) + ", which chose batch " + servedBatch(e) + " (phase " + (e.phase || "-") + ", draw " + (e.draw || "-") + ")");
        if (e.rewards) lines.push("reward [" + e.rewards.map((v) => (v == null ? "-" : v)).join(", ") + "], mean " + fmt(rewardMean(e.rewards)));
        lines.push("u_short " + (e.u_short ? vec(e.u_short) : "no update") + " · u_long " + vec(e.u_long));
      }
    }
    readout.replaceChildren(h("div", { class: "how" }, "dimensions: " + DIMS.join(", ")), ...lines.map((t) => h("div", {}, t)));
  }

  function card(q) {
    const sig = signalsOf(a, q.batch), by = q.e;
    const lines = ["dimensions: " + DIMS.join(", ")];
    if (!hidden) {
      lines.push(by.endpoint === "init" ? "chosen by the initial draw" : "chosen by u_long " + vec(by.u_long) + " (signals of batch " + (by.signal_batch == null ? "-" : by.signal_batch) + ", draw " + (by.draw || "-") + ")");
      lines.push(!sig ? "no request carried the signals of this batch" : "its signals gave u_short " + (sig.u_short ? vec(sig.u_short) : "no update") + " and u_long " + vec(sig.u_long) + ", which chose batch " + servedBatch(sig));
    }
    return {
      title: "Batch " + q.batch + " · mean sum " + fmt(q.b.mean_sum), sub: by.endpoint + (by.request_index != null ? " " + by.request_index : ""), lines,
      posts: q.b.post_ids.map((id, k) => {
        const p = o.posts[id], reward = !hidden && sig && sig.rewards ? sig.rewards[k] : undefined;
        return { head: (k + 1) + ". scores [" + p.scores.join(", ") + "] sum " + p.sum + (p.centered ? " · centered " + vec(p.centered) : "") + " · dwell " + sec(q.b.dwell_ms ? q.b.dwell_ms[k] : null) +
          (reward === undefined ? "" : " · reward " + (reward == null ? "missing" : reward)) + " · " + p.platform, text: p.text + (p.cut ? " [cut]" : "") };
      }),
    };
  }

  const dot = (parent, x, y, r, fill, extra) => el("circle", Object.assign({ cx: x, cy: y, r, fill: css(fill) }, extra || {}), parent);
  const lines = (plot, points, color, Y) => segments(points).forEach((s) => {
    if (s.length > 1) el("path", { d: s.map((p, k) => (k ? "L" : "M") + X(p.x).toFixed(1) + "," + Y(p.y).toFixed(1)).join(""), fill: "none", stroke: css(color), "stroke-width": 1.5, "stroke-linejoin": "round" }, plot);
    s.forEach((p) => dot(plot, X(p.x), Y(p.y), 2.4, color));
  });
  const dimPanel = (title, height, range, valuesAt) => panel(title, height, range, niceTicks(range.lo, range.hi, 4), null, (plot, Y) => {
    DIMS.forEach((d, j) => lines(plot, valuesAt.filter((q) => q.v && q.v[j] != null).map((q) => ({ x: q.x, y: q.v[j] })), DIM_VARS[j], Y));
  });
  const note = (title, msg) => scroll.append(h("div", { class: "trajtitle small-title" }, title), h("p", { class: "how trajtitle" }, msg));

  // ---- 1 batch sums and posts
  const sumHi = Math.max(5, ...batches.flatMap((q) => q.b.post_ids.map((id) => o.posts[id].sum)));
  panel("1. Batch sums and posts", 190, { lo: -0.8, hi: sumHi + 0.8 }, niceTicks(0, sumHi, 4), null, (plot, Y) => {
    batches.forEach((q) => q.b.post_ids.forEach((id, k) => {
      const dw = q.b.dwell_ms ? q.b.dwell_ms[k] : null, r = dwellRadius(dw, capMs, R_MIN, R_MAX);
      const x = X(q.batch + postOffset(k, q.b.post_ids.length, SPREAD)), y = Y(o.posts[id].sum);
      if (r == null) el("circle", { cx: x, cy: y, r: 2.2, fill: "none", stroke: css("--text-muted"), opacity: 0.8 }, plot);
      else dot(plot, x, y, r, "--text-muted", { opacity: 0.45 });
    }));
    const means = batches.filter((q) => q.b.mean_sum != null);
    lines(plot, means.map((q) => ({ x: q.batch, y: q.b.mean_sum })), "--c1", Y);
    means.forEach((q) => bindCard(dot(plot, X(q.batch), Y(q.b.mean_sum), 4.5, "--c1", { stroke: css("--surface-1"), "stroke-width": 1.5, style: "cursor:pointer", "aria-label": "Batch " + q.batch + ", mean sum " + fmt(q.b.mean_sum) }), () => card(q)));
  });

  // ---- 2 batch mean per dimension
  const range = centeredRange(a);
  if (have.batchMeans) dimPanel("2. Batch mean per dimension (score minus inventory mean)", 170, range, batches.map((q) => ({ x: q.batch, v: q.b.mean_centered })));
  else note("2. Batch mean per dimension", "Not in this pull yet.");

  if (hidden) { scroll.append(h("p", { class: "cov trajtitle" }, o.hiddenNote)); }
  else {
    const cols = profileColumns(a, mode);
    // ---- 3 reward
    if (have.rewards) panel("3. Reward per post (line: mean of the posts with a reward)", 130, { lo: -2.5, hi: 1.4 }, [1, 0, -1, -2], (v) => (v === -2 ? "none" : v > 0 ? "+1" : v), (plot, Y) => {
      cols.filter((q) => q.e.rewards).forEach((q) => q.e.rewards.forEach((r, k) => {
        const x = X(q.x + postOffset(k, q.e.rewards.length, SPREAD));
        if (r == null) el("circle", { cx: x, cy: Y(-2), r: 2.4, fill: "none", stroke: css("--text-muted") }, plot);
        else dot(plot, x, Y(r), 2.8, REWARD[r]);
      }));
      lines(plot, cols.map((q) => ({ x: q.x, y: rewardMean(q.e.rewards) })).filter((p) => p.y != null), "--text-primary", Y);
    });
    else note("3. Reward", "Not in this pull yet.");
    if (have.rewards && !cols.some((q) => q.e.rewards)) scroll.append(h("p", { class: "how trajtitle" }, "No request of this attempt has a reward (random condition, warm-up only, or no attention baseline)."));
    // ---- 4 u_short, 5 u_long
    if (have.uShort) dimPanel("4. u_short (updating requests only)", 170, range, cols.map((q) => ({ x: q.x, v: q.e.u_short })));
    else note("4. u_short", "Not in this pull yet.");
    dimPanel("5. u_long", 170, range, cols.map((q) => ({ x: q.x, v: q.e.u_long })));
    // ---- 6 sum and norm
    const ul = cols.filter((q) => q.e.u_long_sum != null);
    const r6 = paddedRange(ul.flatMap((q) => [q.e.u_long_sum, q.e.u_long_norm]));
    panel("6. u_long sum and norm", 140, r6, niceTicks(r6.lo, r6.hi, 4), null, (plot, Y) => {
      lines(plot, ul.map((q) => ({ x: q.x, y: q.e.u_long_sum })), "--text-primary", Y);
      lines(plot, ul.map((q) => ({ x: q.x, y: q.e.u_long_norm })), "--c7", Y);
    });
  }

  const items = DIMS.map((d, j) => ({ label: d, color: css(DIM_VARS[j]) }));
  const lg = h("div", { class: "extra" });
  lg.innerHTML = '<div class="legend"><span>panels 2, 4, 5:</span></div>' + legend(items) +
    legend([{ label: "batch mean of the sum (panel 1)", color: css("--c1") }, { label: "posts, point area = dwell time", color: css("--text-muted"), faint: true }].concat(hidden ? [] : [
      { label: "reward +1", color: css("--c3") }, { label: "reward 0", color: css("--text-muted") }, { label: "reward -1", color: css("--c8") }, { label: "mean reward; u_long sum", color: css("--text-primary") }, { label: "u_long norm", color: css("--c7") }])) +
    '<p class="how">x of every panel: batch index of the attempt, 1-based. The dotted line ends the init and warm-up batches.</p>';
  box.append(lg);

  scroll.scrollLeft = scrolls.get(o.key) || 0;
  scroll.addEventListener("scroll", () => scrolls.set(o.key, scroll.scrollLeft));
}

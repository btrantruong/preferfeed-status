/* Shared by sp1 and sp2: the list of participants of the spot check and the selection bar (one button per
   condition that cycles through that condition's participants, and a dropdown for a specific participant). */
import { h } from "../util.js";
import { lc, CONDITIONS, COND } from "../colors.js";

const keyOf = (u) => u.country + ":" + u.user_id;

/** Participants ordered by condition (CONDITIONS order, others last), newest first within a condition. */
export function orderUsers(users) {
  const rank = (u) => { const i = CONDITIONS.indexOf(u.condition); return i < 0 ? CONDITIONS.length : i; };
  return users.slice().sort((a, b) => rank(a) - rank(b) || b.created_at - a.created_at);
}

/** The participant a click on the button of `condition` selects: the one after `current` in that condition's
    list (wrapping around), or the first of the list (the default pick of the condition if it is there) when
    `current` is not of that condition. null when the condition has no participant. */
export function nextInCondition(users, current, condition) {
  const list = orderUsers(users.filter((u) => u.condition === condition));
  if (!list.length) return null;
  if (current && current.condition === condition) {
    const i = list.findIndex((u) => keyOf(u) === keyOf(current));
    return list[(i + 1) % list.length];
  }
  return list.find((u) => u.default_for) || list[0];
}

/** Draw the selection bar into `box` and return the selected user (or null with a note in the box). */
export function pickUser(box, c) {
  const spot = c.spot;
  if (!spot || !spot.users || !spot.users.length) {
    box.append(h("div", { class: "empty" }, "No participant for the spot check in this pull (it needs the detail pull and INVENTORY_FILE)."));
    return null;
  }
  const pool = orderUsers(spot.users.filter((u) => u.created_at >= c.t0 && u.created_at < c.t1 && (c.state.country === "All" || u.country === c.state.country)));
  if (!pool.length) { box.append(h("div", { class: "empty" }, "No done participant of the list was created in this time range for the selected countries.")); return null; }
  const sel = pool.find((u) => keyOf(u) === c.spotUserKey) || pool.find((u) => u.default_for) || pool[0];

  const select = h("select", { "aria-label": "Participant" });
  const groups = new Map();
  pool.forEach((u) => {
    if (!groups.has(u.condition)) groups.set(u.condition, h("optgroup", { label: lc(u.condition) }));
    const o = h("option", { value: keyOf(u) }, u.country + " · id " + u.user_id + " · " + u.exchanges.length + " exchanges · " + c.fm.fmtDayHM(u.t0_ms));
    if (keyOf(u) === keyOf(sel)) o.selected = true;
    groups.get(u.condition).append(o);
  });
  groups.forEach((g) => select.append(g));
  select.addEventListener("change", () => c.setSpotUser(select.value));

  const bar = h("div", { class: "userbar" });
  const conds = CONDITIONS.concat([...new Set(pool.map((u) => u.condition))].filter((x) => !CONDITIONS.includes(x)));
  conds.forEach((cond) => {
    const n = pool.filter((u) => u.condition === cond).length;
    const here = sel.condition === cond ? pool.filter((u) => u.condition === cond).findIndex((u) => keyOf(u) === keyOf(sel)) + 1 : 0;
    const b = h("button", { type: "button", "aria-pressed": String(sel.condition === cond), style: "border-left:4px solid " + css2(COND[cond] || COND.unknown), title: n ? "Next " + lc(cond) + " participant" : "No " + lc(cond) + " participant in the list" },
      lc(cond) + " (" + (here ? here + "/" : "") + n + ")");
    if (!n) b.disabled = true;
    b.addEventListener("click", () => { const u = nextInCondition(pool, sel, cond); if (u) c.setSpotUser(keyOf(u)); });
    bar.append(b);
  });
  bar.append(h("label", {}, "Participant (database id, never the survey id): "), select);
  box.append(bar);
  return sel;
}

/** A color role of colors.js as a CSS value. */
function css2(role) { return "var(" + role + ")"; }

/** Radius of a post point: its area grows with the dwell time (ms) up to capMs; rMin keeps a short dwell visible. */
export function dwellRadius(ms, capMs, rMin, rMax) {
  if (ms == null || !(ms >= 0)) return null;
  return Math.max(rMin, rMax * Math.sqrt(Math.min(ms, capMs) / capMs));
}

/** Horizontal offset (in batch units) of the k-th of n posts of a batch: spread over +-spread, in served order. */
export function postOffset(k, n, spread) {
  return n <= 1 ? 0 : (k / (n - 1) - 0.5) * 2 * spread;
}

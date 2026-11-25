/* Shared by sp1 and sp2: the list of participants of the spot check and the selection bar. */
import { h } from "../util.js";
import { lc } from "../colors.js";

/** Draw the selection bar into `box` and return the selected user (or null with a note in the box). */
export function pickUser(box, c) {
  const spot = c.spot;
  if (!spot || !spot.users || !spot.users.length) {
    box.append(h("div", { class: "empty" }, "No participant for the spot check in this pull (it needs the detail pull and INVENTORY_FILE)."));
    return null;
  }
  const drawN = c.p.spot_draw_n || 12;
  const key = (u) => u.country + ":" + u.user_id;
  const pool = spot.users.filter((u) => u.created_at >= c.t0 && u.created_at < c.t1 && (c.state.country === "All" || u.country === c.state.country));
  // the list is a random draw of drawN participants; the draw is kept (seed in the browser) until the button is pressed
  const draw = c.spotDraw || { seed: "1" };
  const list = drawSample(pool, drawN, draw.seed, key).sort((a, b) => b.created_at - a.created_at);
  if (!list.length) { box.append(h("div", { class: "empty" }, "No done participant of the list was created in this time range for the selected countries.")); return null; }
  const sel = list.find((u) => key(u) === c.spotUserKey) || list.find((u) => u.default_for) || list[0];
  const select = h("select", { "aria-label": "Participant" }, ...list.map((u) => {
    const o = h("option", { value: key(u) }, u.country + " · id " + u.user_id + " · " + lc(u.condition) + " · " + u.exchanges.length + " exchanges · " + c.fm.fmtDayHM(u.t0_ms) + (u.default_for ? " · default" : ""));
    if (key(u) === key(sel)) o.selected = true;
    return o;
  }));
  select.addEventListener("change", () => c.setSpotUser(select.value));
  const btn = h("button", { type: "button" }, "Draw another batch of users");
  btn.addEventListener("click", () => c.setSpotDraw({ seed: Math.random().toString(36).slice(2, 10) }));
  const bar = h("div", { class: "userbar" }, h("label", {}, "Participant (database id, never the survey id): "), select, btn,
    h("span", {}, list.length + " of " + pool.length));
  box.append(bar);
  return sel;
}

/** Radius of a post point: its area grows with the dwell time (ms) up to capMs; rMin keeps a short dwell visible. */
export function dwellRadius(ms, capMs, rMin, rMax) {
  if (ms == null || !(ms >= 0)) return null;
  return Math.max(rMin, rMax * Math.sqrt(Math.min(ms, capMs) / capMs));
}

/** Horizontal offset (in batch units) of the k-th of n posts of a batch: spread over +-spread, in served order. */
export function postOffset(k, n, spread) {
  return n <= 1 ? 0 : (k / (n - 1) - 0.5) * 2 * spread;
}

/** 32-bit hash of a string (xmur3), the seed of the generator below. */
export function seedHash(str) {
  let h = 1779033703 ^ str.length;
  for (let i = 0; i < str.length; i++) { h = Math.imul(h ^ str.charCodeAt(i), 3432918353); h = (h << 13) | (h >>> 19); }
  h = Math.imul(h ^ (h >>> 16), 2246822507); h = Math.imul(h ^ (h >>> 13), 3266489909);
  return (h ^ (h >>> 16)) >>> 0;
}

/** Seeded generator (mulberry32): returns a function giving numbers in [0, 1). */
export function mulberry32(a) {
  return () => {
    a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** n items drawn without replacement from `items`, the same for the same seed whatever the order of `items`
    (they are sorted by key(item) first); all of them if n >= items.length. */
export function drawSample(items, n, seed, key) {
  const a = items.slice().sort((x, y) => (key(x) < key(y) ? -1 : key(x) > key(y) ? 1 : 0));
  if (n >= a.length) return a;
  const rnd = mulberry32(seedHash(String(seed)));
  for (let i = 0; i < n; i++) { const j = i + Math.floor(rnd() * (a.length - i)); [a[i], a[j]] = [a[j], a[i]]; }
  return a.slice(0, n);
}

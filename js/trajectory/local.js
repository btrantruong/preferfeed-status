/* Entry of the local view (pipeline/local_view.py puts this module, its imports and the data into one HTML file).
   Picks a participant and an attempt, then draws the trajectory panels. Row-level data: never published. */
import { renderTrajectory } from "./view.js";
import { h, store } from "../util.js";
import { CONDITIONS, lc } from "../colors.js";

const D = JSON.parse(document.getElementById("data").textContent);
const keyOf = (u) => u.country + ":" + u.user_id;
const S = Object.assign({ country: "all", condition: "all", done: "all", search: "", user: "", attempt: null }, JSON.parse(store("traj.state") || "{}"));
const save = () => store("traj.state", JSON.stringify(S));
const when = (ms) => new Date(ms).toISOString().slice(0, 16).replace("T", " ") + " UTC";

const pick = h("div", { class: "userbar" }), info = h("p", { class: "how" }), host = h("div", { class: "chart" });
document.getElementById("app").append(h("section", { class: "card" }, pick, info, host));

function select(label, value, options, onChange) {
  const s = h("select", { "aria-label": label });
  options.forEach(([v, t]) => { const o = h("option", { value: v }, t); if (String(v) === String(value)) o.selected = true; s.append(o); });
  s.addEventListener("change", () => onChange(s.value));
  return h("label", {}, label + " ", s);
}

function filtered() {
  return D.users.filter((u) => (S.country === "all" || u.country === S.country) && (S.condition === "all" || u.condition === S.condition) &&
    (S.done === "all" || (S.done === "done") === !!u.done) && (!S.search || String(u.user_id) === S.search.trim()));
}

function render() {
  const list = filtered();
  const user = list.find((u) => keyOf(u) === S.user) || list[0];
  const countries = [...new Set(D.users.map((u) => u.country))];
  const set = (patch) => { Object.assign(S, patch); save(); render(); };
  const step = (d) => { const i = list.indexOf(user); const u = list[(i + d + list.length) % list.length]; set({ user: keyOf(u), attempt: null }); };
  const search = h("input", { type: "text", inputmode: "numeric", value: S.search, placeholder: "id" });
  search.addEventListener("change", () => set({ search: search.value, user: "", attempt: null }));
  pick.replaceChildren();
  if (countries.length > 1) pick.append(select("country", S.country, [["all", "all"], ...countries.map((c) => [c, c])], (v) => set({ country: v })));
  pick.append(select("condition", S.condition, [["all", "all"], ...CONDITIONS.map((c) => [c, lc(c)])], (v) => set({ condition: v })),
    select("status", S.done, [["all", "all"], ["done", "done"], ["notdone", "not done"]], (v) => set({ done: v })),
    h("label", {}, "database id ", search));
  if (!user) { info.textContent = "No participant matches."; host.replaceChildren(); return; }
  const prev = h("button", { type: "button" }, "‹ Previous"), next = h("button", { type: "button" }, "Next ›");
  prev.addEventListener("click", () => step(-1)); next.addEventListener("click", () => step(1));
  const nBatches = (u) => Math.max(0, ...u.attempts.flatMap((a) => a.exchanges.flatMap((e) => e.batches.map((b) => b.batch))));
  const k = S.attempt != null && S.attempt < user.attempts.length ? S.attempt : user.attempts.length - 1;
  pick.append(prev, next, select("participant (" + list.length + ")", keyOf(user), list.map((u) => [keyOf(u), u.country + " · id " + u.user_id + " · " + lc(u.condition) + (u.done ? " · done" : " · not done") + " · " + nBatches(u) + " batches"]), (v) => set({ user: v, attempt: null })),
    select("attempt", k, user.attempts.map((a, i) => [i, (i + 1) + " of " + user.attempts.length + " (" + a.exchanges.length + " requests)"]), (v) => set({ user: keyOf(user), attempt: +v })));
  const a = user.attempts[k];
  info.textContent = user.country + " id " + user.user_id + ", " + lc(user.condition) + ", " + (user.done ? "done" : user.cancelled ? "not done, cancelled" : "not done") + ", created " + when(user.created_at) + "; this attempt started " + when(a.t0_ms) + ".";
  renderTrajectory(host, { attempt: a, posts: D.posts, key: keyOf(user) + ":" + k, mode: store("pfs.traj.mode") || "informed",
    onMode: (m) => { store("pfs.traj.mode", m); render(); }, capS: D.meta.dwell_cap_s, alpha: D.meta.alpha, hiddenNote: "" });
}

let resize = null;
window.addEventListener("resize", () => { clearTimeout(resize); resize = setTimeout(render, 150); });
render();

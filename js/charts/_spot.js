/* Shared by sp1 and sp2: the list of participants of the local spot check and the selection bar. */
import { h } from "../util.js";
import { lc } from "../colors.js";

/** Draw the selection bar into `box` and return the selected user (or null with a note in the box). */
export function pickUser(box, c) {
  const spot = c.spot;
  if (!spot || !spot.users || !spot.users.length) {
    box.append(h("div", { class: "empty" }, "No participant for the spot check in this pull (it needs the detail pull and INVENTORY_FILE)."));
    return null;
  }
  const maxN = c.p.spot_max_users || 30;
  const list = spot.users.filter((u) => u.created_at >= c.t0 && u.created_at < c.t1 && (c.state.country === "All" || u.country === c.state.country)).slice(0, maxN);
  if (!list.length) { box.append(h("div", { class: "empty" }, "No done participant of the list was created in this time range for the selected countries.")); return null; }
  const key = (u) => u.country + ":" + u.user_id;
  const sel = list.find((u) => key(u) === c.spotUserKey) || list.find((u) => u.default_for) || list[0];
  const select = h("select", { "aria-label": "Participant" }, ...list.map((u) => {
    const o = h("option", { value: key(u) }, u.country + " · id " + u.user_id + " · " + lc(u.condition) + " · " + u.exchanges.length + " exchanges · " + c.fm.fmtDayHM(u.t0_ms) + (u.default_for ? " · default" : ""));
    if (key(u) === key(sel)) o.selected = true;
    return o;
  }));
  select.addEventListener("change", () => c.setSpotUser(select.value));
  box.append(h("div", { class: "userbar" }, h("label", {}, "Participant (database id, never the survey id): "), select));
  return sel;
}

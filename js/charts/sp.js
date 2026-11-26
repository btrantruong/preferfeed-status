/* E1. User spot check: the trajectory of one participant, stacked panels on one batch axis (../trajectory/view.js). */
import { pickUser } from "./_spot.js";
import { renderTrajectory } from "../trajectory/view.js";
import { h, store } from "../util.js";

const MODE_KEY = "pfs.traj.mode";

export default {
  id: "sp", title: "Participant trajectory", files: [], window: "created",
  caption: (meta) => {
    const p = meta.params || {};
    return "x of every panel: batch index of the final attempt (batches 1 and 2 come from the init request; a next_batch request carries the signals of batch t and serves batch t + 2). Panel 1: sum of the five scores (0 to 15) of each post, point area proportional to its dwell time (capped at " + (p.spot_dwell_cap_s || 30) + " s), and the batch mean. Panel 2: per dimension, the mean over the posts of the batch of score minus the inventory mean of the country. Panel 3: reward of each post, rebuilt from the logged signals (attention: +1, 0 or -1 from the dwell per word against the warm-up baseline, band " + (p.reward_eta == null ? "" : "+-" + p.reward_eta) + "; preference: the vote), and the mean. Panel 4: u_short = sum r c / sum |r| of the request, only where it updated the profile. Panel 5: u_long after the request. Panel 6: sum and Euclidean norm of u_long. Panels 2, 4 and 5 share their y range. Posts come from the project's inventory by post_id; the participant is identified by database id." +
      (p.spot_profile_conditions ? " Panels 3 to 6 are published for these conditions only: " + p.spot_profile_conditions.join(", ").toLowerCase() + "." : "");
  },
  how: "The toggle moves panels 3 to 6 by two batches: read a column as the batch that informed the profile, or as the batch the profile chose.",
  draw(box, c) {
    box.replaceChildren();
    if (c.spot && c.spot.local_full) box.append(h("p", { class: "cov" }, "Local full view: includes votes, not published. Spot data as of " + c.fm.fmtDayHM(Date.parse(c.spot.as_of)) + "."));
    const u = pickUser(box, c); if (!u) return;
    const host = h("div"); box.append(host);
    const draw = () => renderTrajectory(host, {
      attempt: u, posts: c.spot.posts, key: u.country + ":" + u.user_id, mode: store(MODE_KEY) || "informed",
      onMode: (m) => { store(MODE_KEY, m); draw(); }, capS: c.p.spot_dwell_cap_s, alpha: c.p.algo_alpha,
      hiddenNote: u.profile_hidden ? "Rewards, u_short and u_long are not published for the " + String(u.condition).toLowerCase() + " condition: its rewards are the participant's votes." : "",
    });
    draw();
  },
};

/* D3. Integrity-flag rate over time, one small panel per flag. */
import { barPlot } from "../plots.js";
import { rebin } from "../select.js";
import { infoButton } from "../popover.js";
import { h } from "../util.js";

export const FLAGS = [
  ["no_records", "No record_entry rows. The participant is done, but the behaviour tracking (mouse, scroll and what was visible, about 40 rows per focused second) stored nothing for the final attempt, so there is no behavioural data for them."],
  ["no_init", "No init exchange. The first call of the feed to the algorithm server (it returns the first ten posts) is missing from algo_exchange for the final attempt."],
  ["no_next_batch", "No next_batch exchange. The participant never asked the algorithm for a further batch of posts (or those calls were not stored), although they finished."],
  ["request_gap", "Request gap. The request_index values of the final attempt are not 0, 1, 2, ... without a hole, so at least one algorithm request was lost or not stored. Retaking participants are judged on their last attempt only."],
  ["condition_mismatch", "Condition mismatch. A next_batch exchange used an algorithm that is neither RANDOM nor the participant's assigned condition, so the participant may have been served by the wrong arm."],
  ["never_left_warmup", "Warning: never left warm-up. A participant of the attention or preference condition has next_batch exchanges but none reached algo_state.phase algorithm (the exchanges stayed in the warm-up or waiting phase). If phase is not stored, the algorithm type is used instead. Random participants are not checked."],
];

export default {
  id: "dc1", title: "Integrity-flag rate over time", files: ["flags.csv"], window: "created",
  caption: (meta) => "x: session creation time in bins of " + ((meta.params || {}).flag_bin_minutes || 60) + " minutes from the launch (created_at). y: share of the done participants created in the bin who carry the flag, in percent; the top panel gives the number of done participants per bin. Bins with fewer than " + ((meta.params || {}).min_n_rate || 5) + " done participants are drawn faded. Flags are evaluated on the final attempt of each participant (the logic of check_user() in daily_check.py).",
  how: "It shows done participants whose behavioural or algorithm logs are missing. Click or hover the i beside a flag for its definition.",
  draw(box, c) {
    box.replaceChildren();
    const fbin = (c.p.flag_bin_minutes || 60) * 60000, minN = c.p.min_n_rate || 5;
    const cols = ["n_done", ...FLAGS.map((f) => f[0])];
    const rows = rebin(c.rows("flags.csv"), c.launchMs, fbin, [], cols);
    const first = Math.floor((c.t0 - c.launchMs) / fbin), last = Math.max(first, Math.ceil((c.t1 - c.launchMs) / fbin) - 1);
    const idx = []; for (let b = first; b <= last; b++) idx.push(b);
    const byBin = new Map(rows.map((r) => [r.bin, r]));
    const get = (b, k) => (byBin.get(b) ? byBin.get(b)[k] : 0);
    const labels = idx.map((b) => c.fm.fmtHM(c.launchMs + b * fbin));
    const nDone = idx.map((b) => get(b, "n_done"));
    const faint = (i) => nDone[i] < minN;
    const tot = nDone.reduce((a, b) => a + b, 0);
    const add = (title, info, cfg) => {
      const wrap = h("div", { class: "dcsub" });
      const head = h("div", { class: "small-title" }, title, info ? infoButton(title, info) : null);
      const sub = h("div", { class: "chart sub" });
      wrap.append(head, sub); box.append(wrap);
      barPlot(sub, Object.assign({ labels, height: 84, margin: { l: 40, t: 6, b: 22 }, minLabelPx: 56 }, cfg));
    };
    add("Done participants per bin (n)", "Number of done participants created in the bin; the share in each panel below is computed from it.", {
      series: [{ name: "done", color: "--text-muted", values: nDone }],
      tip: (i) => "<b>" + labels[i] + "</b><br>done: " + nDone[i] });
    FLAGS.forEach(([k, info]) => {
      const v = idx.map((b) => get(b, k));
      const share = v.map((x, i) => (nDone[i] ? (100 * x) / nDone[i] : 0));
      add(k + (k === "never_left_warmup" ? " (warning)" : ""), info, {
        series: [{ name: k, color: k === "never_left_warmup" ? "--c4" : "--c1", values: share }], ticks: { step: 50, max: 100, ticks: [0, 50, 100] },
        fmtY: (t) => t + "%", faint,
        tip: (i) => "<b>" + labels[i] + "</b><br>" + k + ": " + v[i] + " of " + nDone[i] + " done (" + share[i].toFixed(0) + "%)" + (faint(i) ? '<br><span class="muted">fewer than ' + minN + " done participants</span>" : "") });
    });
    if (!tot) box.append(h("div", { class: "empty" }, "No done participants in this time range."));
  },
};

/* Window, country and re-binning functions. Pure: no DOM, tested with node --test.

   A row has bin_start (UTC ISO 8601). Participant files are binned by session creation in bins of
   meta.bin_minutes ("created"), event files by the event time in bins of meta.event_bin_minutes ("event").
   The window is [from, to) in participant bins counted from the launch; for event files it is the same
   time span. A country keeps its rows, "All" sums them (the meaning of the live page). */

export const NUMERIC = new Set(["n", "n_done", "no_records", "no_init", "no_next_batch", "request_gap",
  "condition_mismatch", "never_left_warmup", "any_fail", "step", "attempts", "after_stop", "age_bin",
  "records_bin", "requests", "diff", "request_index", "n_active", "n_algorithm", "started", "has_server_error"]);

/** CSV text to row objects (no quoted commas occur in the published files). */
export function parseCSV(text) {
  const lines = text.trim().split(/\r?\n/);
  if (lines.length < 2) return [];
  const head = lines[0].split(",");
  return lines.slice(1).map((line) => {
    const v = line.split(",");
    const o = {};
    head.forEach((k, i) => { o[k] = NUMERIC.has(k) ? +v[i] : v[i]; });
    return o;
  });
}

/** Add t (ms of bin_start) and idx (bin index from the launch, bins of binMs) to each row. */
export function indexRows(rows, launchMs, binMs) {
  rows.forEach((r) => {
    r.t = Date.parse(r.bin_start);
    r.idx = Math.round((r.t - launchMs) / binMs);
  });
  return rows;
}

/** Rows inside the window. w = {from, to, launchMs, binMs}; kind "created" uses idx, "event" uses t. */
export function inWindow(rows, kind, w) {
  const t0 = w.launchMs + w.from * w.binMs, t1 = w.launchMs + w.to * w.binMs;
  return rows.filter((r) => (kind === "created" ? r.idx >= w.from && r.idx < w.to : r.t >= t0 && r.t < t1));
}

export function byCountry(rows, country) {
  return country === "All" ? rows : rows.filter((r) => r.country === country);
}

/** Sum the value columns over rows that share the key columns (countries are pooled when "country" is not a key). */
export function pool(rows, keys, vals) {
  vals = vals || ["n"];
  const m = new Map();
  rows.forEach((r) => {
    const k = keys.map((c) => r[c]).join("\u0001");
    let o = m.get(k);
    if (!o) { o = {}; keys.forEach((c) => { o[c] = r[c]; }); vals.forEach((c) => { o[c] = 0; }); m.set(k, o); }
    vals.forEach((c) => { o[c] += r[c]; });
  });
  return [...m.values()];
}

/** Re-bin rows onto bins of binMs from launchMs: adds bin (index) and sums the value columns per key. */
export function rebin(rows, launchMs, binMs, keys, vals) {
  const withBin = rows.map((r) => Object.assign({}, r, { bin: Math.floor((r.t - launchMs) / binMs) }));
  return pool(withBin, ["bin"].concat(keys), vals);
}

/** Open-ended bins: values from `top` and above share the last bin. */
export function capAt(v, top) { return v >= top ? top : v; }

/** Number of bins from the launch up to the last data or pull time. */
export function countBins(rows, launchMs, binMs, pulledMs) {
  let last = pulledMs;
  rows.forEach((r) => { last = Math.max(last, launchMs + (r.idx + 1) * binMs); });
  return Math.max(0, Math.ceil((last - launchMs) / binMs));
}

/** Countries of the selection that have no data for a file, and those whose data is older than the pull.
    info = meta.files[name]; returns {missing: [...], older: {cc: iso}}. */
export function coverage(info, countries, selected, pulledIso) {
  const list = selected === "All" ? countries : [selected];
  const asOf = (info && info.as_of) || {};
  const missing = list.filter((c) => !asOf[c]);
  const older = {};
  list.forEach((c) => { if (asOf[c] && asOf[c] !== pulledIso) older[c] = asOf[c]; });
  return { missing, older };
}

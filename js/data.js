/* Loads meta.json and the files listed in meta.files (a file that is absent or fails is skipped), and, on the
   local preview only, local/spot_users.json (one participant's data; it does not exist on GitHub Pages). */
import { parseCSV, indexRows } from "./select.js";

export async function loadAll(base) {
  const t = "?t=" + Date.now();
  const getJSON = (url) => fetch(url + t, { cache: "no-store" }).then((r) => { if (!r.ok) throw new Error(url + " " + r.status); return r.json(); });
  const meta = await getJSON(base + "meta.json");
  const launchMs = Date.parse(meta.launch_utc);
  const binMs = meta.bin_minutes * 60000, eventMs = (meta.event_bin_minutes || meta.bin_minutes) * 60000;
  const files = {};
  // an older meta.json has no file registry: only status_bins.csv exists
  const listed = meta.files || { "status_bins.csv": { window: "created" } };
  await Promise.all(Object.entries(listed).map(async ([name, info]) => {
    try {
      const r = await fetch(base + name + t, { cache: "no-store" });
      if (!r.ok) return;
      files[name] = indexRows(parseCSV(await r.text()), launchMs, info.window === "event" ? eventMs : binMs);
    } catch (e) { /* the page tolerates a missing file */ }
  }));
  return { meta, files, launchMs, binMs, eventMs };
}

/** Does the local-only spot check file exist? (HEAD request; false on GitHub Pages.) */
export async function spotExists() {
  try { return (await fetch("local/spot_users.json", { method: "HEAD", cache: "no-store" })).ok; } catch (e) { return false; }
}

export async function loadSpot() {
  const r = await fetch("local/spot_users.json?t=" + Date.now(), { cache: "no-store" });
  if (!r.ok) throw new Error("spot_users.json " + r.status);
  return r.json();
}

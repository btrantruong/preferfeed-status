/* preferFeed fielding status page: boot, state (country, window, page per panel), refresh loop.
   Reads data/meta.json and the files it lists (or ?data=<base url>/). All times are shown in meta.tz; the data
   files are in UTC. The country toggle selects the countries for every figure: All pools them, a click keeps one. */
import { $, store, esc, css, h, makeFormatters, ago } from "./util.js";
import { loadAll, spotExists, loadSpot } from "./data.js";
import { inWindow, byCountry, pool, countBins, coverage } from "./select.js";
import { createSlider } from "./slider.js";
import { createPager, clampPage } from "./pager.js";
import { emptyNote } from "./svg.js";
import { PANELS, TOP } from "./panels.js";

const params = new URLSearchParams(location.search);
const BASE = (params.get("data") || "data/").replace(/\/?$/, "/");
const S = { country: store("pfs.country") || "All", from: 0, to: 0, toAtEnd: true };
let D = null, fm = null, nBins = 0, slider = null, timer = null;
let spot = null, spotAvailable = false, spotLoaded = false;
const panelUI = {};   // panel id -> {pager, titleEl, capEl, howEl, covEl, box, page}

// ---- context handed to the charts -----------------------------------------------------------------------
function windowOf() { return { from: S.from, to: S.to, launchMs: D.launchMs, binMs: D.binMs }; }

function makeCtx(spec) {
  const meta = D.meta, w = windowOf();
  const countries = Object.keys(meta.countries);
  const win = (file) => inWindow(D.files[file] || [], (meta.files && meta.files[file] ? meta.files[file].window : spec.window), w);
  return {
    meta, state: S, w, fm, countries, launchMs: D.launchMs, binMs: D.binMs, eventMs: D.eventMs, nBins,
    p: meta.params || {},
    has: (file) => !!D.files[file],
    windowRows: win,
    rows: (file) => byCountry(win(file), S.country),
    pool: (file, keys, vals) => pool(byCountry(win(file), S.country), keys, vals),
    t0: D.launchMs + S.from * D.binMs, t1: D.launchMs + S.to * D.binMs,
    who: S.country === "All" ? "all countries" : S.country,
    spot, spotUserKey: store("pfs.spotUser"),
    setSpotUser: (k) => { store("pfs.spotUser", k); renderCharts(); },
  };
}

// ---- header and info ------------------------------------------------------------------------------------
function renderHeader() {
  const meta = D.meta, pulledMs = Date.parse(meta.pulled_at);
  $("sub").textContent = "Participants counted from launch, " + fm.fmtDayHM(D.launchMs) + " " + fm.zoneName(D.launchMs) + ". Times are shown in " + meta.tz + ".";
  const parts = Object.entries(meta.countries).map(([c, info]) => {
    if (info.status === "not_pulled") return "<span>" + esc(c) + ": " + (info.as_of ? "not pulled in this run, data as of " + esc(fm.fmtHM(Date.parse(info.as_of))) + " (" + ago(Date.parse(info.as_of)) + ")" : "not launched or not pulled yet") + "</span>";
    if (info.status === "ok") return "<span>" + esc(c) + ": pulled " + esc(fm.fmtHM(Date.parse(info.as_of))) + " (" + ago(Date.parse(info.as_of)) + ")</span>";
    if (info.as_of) return '<span class="failed">' + esc(c) + ": last pull failed, data as of " + esc(fm.fmtHM(Date.parse(info.as_of))) + " (" + ago(Date.parse(info.as_of)) + ")</span>";
    return '<span class="failed">' + esc(c) + ": no data yet (server not reached)</span>";
  });
  $("pulls").innerHTML = "Last pull " + esc(fm.fmtDayHM(pulledMs)) + " (" + ago(pulledMs) + "). " + parts.join(" ");
  const stale = meta.stale_after_min && (Date.now() - pulledMs) / 60000 > meta.stale_after_min;
  $("warn").innerHTML = stale ? '<div class="warn" role="status">The data is older than ' + meta.stale_after_min + " minutes; updates may have stopped.</div>" : "";
  renderInfo();
  $("footer").innerHTML = (spotAvailable ? "Aggregate counts, except panel E (see About the data). " : "Aggregate counts only; no individual data is published. ") + "Scripts: <a href=\"" + esc(meta.scripts_url) + "\">" +
    esc(meta.scripts_url.replace(/^https?:\/\//, "")) + "</a>" + (meta.code_version ? " (version " + esc(meta.code_version) + ")" : "") + ".";
}

function renderInfo() {
  const meta = D.meta, ignore = meta.ignore_codes.length ? meta.ignore_codes.join(", ") : "none";
  // countries that launch later than the first one count from their own launch time
  const later = Object.entries(meta.countries).filter(([, i]) => i.launch_utc && i.launch_utc !== meta.launch_utc)
    .map(([c, i]) => "<b>" + esc(c) + " launch:</b> " + esc(c) + " is counted from " + esc(fm.fmtDayHM(Date.parse(i.launch_utc))) + " " + esc(fm.zoneName(Date.parse(i.launch_utc))) + ".");
  const items = [
    "<b>Who is counted:</b> every participant whose session was created on or after " + esc(fm.fmtDayHM(D.launchMs)) + " (" + esc(meta.tz) + "), per country server. One participant is one row in the study database.",
    ...later,
    "<b>Time window:</b> the two handles of the slider select participants by the time their session was created, in steps of " + meta.bin_minutes + " minutes. Charts of participants use that window; charts of events (server errors, algorithm calls) use the events whose time lies inside it. Counts are the status of those participants at the last pull (shown at the top). A participant's status can still change after they are counted, for example after a restart.",
    "<b>Country:</b> All pools the countries by summing their counts; a click on a country keeps that country alone. The choice applies to every figure.",
    "<b>done:</b> reached the end page through the study timer.",
    "<b>cancelled:</b> the session was stopped by the study software. There is no cancel button for participants; a session is stopped when an automated browser is detected (bot), when the participant did not focus on the feed or view enough posts by the end (idle: under " + meta.idle_min_seconds + " s focused or under " + meta.idle_min_posts + " posts viewed), or when the timeline page was reloaded (reload). other means stopped without one of these three reasons.",
    "<b>Several codes and retakes:</b> a participant can be stopped, restart (allowed after bot or idle detection; a participant who is done cannot start again) and be stopped again. A restart sets the status back to incomplete, so a retake is recognised by its recorded attempt and by the stop that came before it. The reason shown is the last stop. Each participant is counted once, so the shares add up to 100%.",
    "<b>incomplete:</b> neither done nor stopped. These participants left before the end or are still in their session (sessions last up to about 10 minutes). possibly in session marks those who started less than " + meta.session_min + " minutes before the last pull. error logged means at least one technical error was recorded (ignoring " + esc(ignore) + ").",
    "<b>Data and code:</b> " + (spotAvailable ? "aggregate counts, except panel E. Panel E shows, for a list of participants identified by their database id (not their survey id), the posts they were served, the time they spent on each post and the profile estimated by the algorithm; it contains no survey answers or other personal data. " : "aggregate counts only; no individual data is published. ") + "Scripts: <a href=\"" + esc(meta.scripts_url) + "\">" + esc(meta.scripts_url.replace(/^https?:\/\//, "")) + "</a>" + (meta.code_version ? " (version " + esc(meta.code_version) + ")" : "") + ".",
  ];
  $("info-body").innerHTML = "<ul>" + items.map((t) => "<li>" + t + "</li>").join("") + "</ul>";
}

// ---- controls -------------------------------------------------------------------------------------------
function setupCountries() {
  const box = $("country");
  box.innerHTML = "";
  ["All"].concat(Object.keys(D.meta.countries)).forEach((c) => {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = c; b.setAttribute("aria-pressed", String(c === S.country));
    const info = D.meta.countries[c];
    if (info && info.status === "not_pulled" && !info.as_of) { b.classList.add("nodata"); b.title = c + " is not launched or not pulled yet"; }
    b.addEventListener("click", () => { S.country = c; store("pfs.country", c); setupCountries(); renderCharts(); });
    box.appendChild(b);
  });
  if (S.country !== "All" && !(S.country in D.meta.countries)) { S.country = "All"; setupCountries(); }
}

function sliderLabel(which, v) {
  return (which === "from" ? "from " : "to ") + fm.fmtDayHM(D.launchMs + v * D.binMs) + " " + fm.zoneName(D.launchMs + v * D.binMs);
}

function setupRange() {
  if (S.toAtEnd || S.to > nBins) S.to = nBins;
  if (S.from >= S.to) S.from = Math.max(0, S.to - 1);
  if (!slider) {
    slider = createSlider($("slider"), {
      max: nBins, from: S.from, to: S.to, minGap: 1, pageStep: Math.max(1, Math.round(60 / D.meta.bin_minutes)),
      label: sliderLabel,
      onChange: (v) => { S.from = v.from; S.to = v.to; S.toAtEnd = v.to === slider.get().max; renderCharts(); },
    });
  }
  slider.set(nBins, S.from, S.to);
  $("range2").style.display = nBins > 0 ? "" : "none";
}

function setupRefresh() {
  const auto = $("auto");
  const saved = store("pfs.auto");
  auto.checked = saved === null ? true : saved === "1";
  auto.addEventListener("change", () => { store("pfs.auto", auto.checked ? "1" : "0"); schedule(); });
  $("refresh").addEventListener("click", load);
}

function schedule() {
  if (timer) clearInterval(timer);
  timer = null;
  const min = D ? D.meta.refresh_min : 2;
  $("refresh-min").textContent = String(min);
  if ($("auto").checked) timer = setInterval(load, min * 60000);
}

// ---- panels ---------------------------------------------------------------------------------------------
// ?only=B shows one panel and ?pages=B:3,D:1 opens pages (0-based) without storing them: for checking the figures
const ONLY = params.get("only"), START_PAGES = Object.fromEntries((params.get("pages") || "").split(",").filter(Boolean).map((s) => s.split(":")));
function visiblePanels() { return PANELS.filter((p) => (p.needs !== "spot" || spotAvailable) && (!ONLY || p.id === ONLY)); }

function buildPanels() {
  const root = $("panels");
  root.replaceChildren();
  visiblePanels().forEach((panel) => {
    const pagerBox = h("div", { class: "pager" });
    const ui = {
      title: h("p", { class: "page-title" }), box: h("div", { class: "chart" }), cap: h("p", { class: "caption" }),
      how: h("p", { class: "how" }), cov: h("div"),
    };
    root.append(h("section", { class: "card panel", "aria-labelledby": "ph-" + panel.id },
      h("h2", { id: "ph-" + panel.id }, panel.id + ". " + panel.title), pagerBox, ui.title, ui.box, ui.cov, ui.cap, ui.how));
    const saved = clampPage(panel.id in START_PAGES ? +START_PAGES[panel.id] : +store("pfs.page." + panel.key) || 0, panel.pages.length);
    ui.page = saved;
    ui.pager = createPager(pagerBox, { onPage: (k) => { ui.page = k; if (!(panel.id in START_PAGES)) store("pfs.page." + panel.key, String(k)); drawPanel(panel); } });
    ui.pager.set(saved, panel.pages.map((p) => (p.group ? p.group + ": " : "") + p.title));
    panelUI[panel.id] = ui;
  });
}

function drawPanel(panel) {
  const ui = panelUI[panel.id], spec = panel.pages[ui.page];
  ui.title.replaceChildren(...(spec.group ? [h("span", { class: "group" }, spec.group + " · ")] : []), spec.title);
  ui.cap.textContent = typeof spec.caption === "function" ? spec.caption(D.meta) : spec.caption || "";
  ui.how.textContent = spec.how || "";
  ui.cov.replaceChildren();
  const missing = spec.files.filter((f) => !D.files[f]);
  if (missing.length) { emptyNote(ui.box, "Not in this pull yet (" + missing.join(", ") + ")."); return; }
  if (nBins === 0) { emptyNote(ui.box, "No participants yet. Launch: " + fm.fmtDayHM(D.launchMs) + " " + fm.zoneName(D.launchMs) + "."); return; }
  const c = makeCtx(spec);
  ui.box.replaceChildren();
  try { spec.draw(ui.box, c); } catch (e) { emptyNote(ui.box, "This figure could not be drawn (" + e.message + ")."); console.error(e); }
  const notes = [];
  spec.files.forEach((f) => {
    const cov = coverage(D.meta.files && D.meta.files[f], c.countries, S.country, D.meta.pulled_at);
    if (cov.missing.length) notes.push("No data for " + cov.missing.join(", ") + " in " + f + " (not available in that database or not pulled).");
    Object.entries(cov.older).forEach(([cc, t]) => notes.push(cc + ": data of this figure is as of " + fm.fmtHM(Date.parse(t)) + " (last pull of it failed or was skipped)."));
  });
  if (notes.length) ui.cov.replaceChildren(...[...new Set(notes)].map((t) => h("div", { class: "cov" }, t)));
}

function renderCharts() {
  if (!D) return;
  $("from-out").textContent = nBins ? fm.fmtDayHM(D.launchMs + S.from * D.binMs) : "";
  $("to-out").textContent = nBins ? fm.fmtDayHM(D.launchMs + S.to * D.binMs) : "";
  const who = S.country === "All" ? "all countries" : S.country;
  $("c1-title").textContent = "Participants since launch, " + who;
  if (ONLY) $("top").style.display = "none";
  if (nBins === 0) {
    emptyNote($("c1"), "No participants yet. Launch: " + fm.fmtDayHM(D.launchMs) + " " + fm.zoneName(D.launchMs) + ".");
    $("c1-note").textContent = "";
  } else {
    const c = makeCtx(TOP);
    $("c1-note").textContent = TOP.caption(D.meta, c);
    try { TOP.draw($("c1"), c); } catch (e) { emptyNote($("c1"), "This figure could not be drawn (" + e.message + ")."); console.error(e); }
  }
  visiblePanels().forEach(drawPanel);
}

// ---- load -----------------------------------------------------------------------------------------------
async function load() {
  try {
    D = await loadAll(BASE);
  } catch (e) {
    $("sub").textContent = "Could not load the data (" + e.message + "). Try Refresh.";
    return;
  }
  fm = makeFormatters(D.meta.tz);
  nBins = countBins(D.files["status_bins.csv"] || [], D.launchMs, D.binMs, Date.parse(D.meta.pulled_at));
  const hadSpot = spotAvailable;
  spotAvailable = await spotExists();
  if (spotAvailable) { try { spot = await loadSpot(); spotLoaded = true; } catch (e) { spot = null; } }
  setupCountries(); renderHeader(); schedule(); setupRange();
  if (hadSpot !== spotAvailable || !Object.keys(panelUI).length) buildPanels();
  renderCharts();
}

setupRefresh();
let resizeT = null;
window.addEventListener("resize", () => { clearTimeout(resizeT); resizeT = setTimeout(renderCharts, 150); });
setInterval(() => { if (D) renderHeader(); }, 60000);
const mq = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
if (mq && mq.addEventListener) mq.addEventListener("change", renderCharts);
load();

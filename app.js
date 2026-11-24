/* preferFeed fielding status page. Reads data/meta.json and data/status_bins.csv
   (or ?data=<base url>/), and draws two charts for the selected country and time range.
   All times are shown in meta.tz; the data files are in UTC. */
(function () {
  "use strict";

  const params = new URLSearchParams(location.search);
  const DATA = (params.get("data") || "data/").replace(/\/?$/, "/");
  const STATUSES = ["done", "cancelled", "incomplete"];
  const STATUS_VAR = { done: "--s-done", cancelled: "--s-cancelled", incomplete: "--s-incomplete" };
  const LABEL = {
    done: "done", cancelled: "cancelled", incomplete: "incomplete",
    bot: "bot", idle: "idle", reload: "reload", other: "other",
    in_session: "possibly in session", error_logged: "error logged", no_error: "no error",
  };
  const SVGNS = "http://www.w3.org/2000/svg";

  let meta = null;
  let rows = [];
  let launchMs = 0, binMs = 0, nBins = 0;
  const state = { country: store("pfs.country") || "All", from: 0, to: 0, toAtEnd: true };
  let timer = null;

  // ---------- small helpers ----------
  function store(key, value) {
    try {
      if (value === undefined) return localStorage.getItem(key);
      localStorage.setItem(key, value);
    } catch (e) { return null; }
    return null;
  }
  const $ = (id) => document.getElementById(id);
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  function el(tag, attrs, parent) {
    const node = document.createElementNS(SVGNS, tag);
    for (const k in attrs) node.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(node);
    return node;
  }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function fmt(ms, opts) {
    return new Intl.DateTimeFormat("en-GB", Object.assign({ timeZone: meta.tz, hourCycle: "h23" }, opts)).format(new Date(ms));
  }
  const fmtHM = (ms) => fmt(ms, { hour: "2-digit", minute: "2-digit" });
  const fmtDayHM = (ms) => fmt(ms, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  function zoneName(ms) {
    const part = new Intl.DateTimeFormat("en-GB", { timeZone: meta.tz, timeZoneName: "short" })
      .formatToParts(new Date(ms)).find((p) => p.type === "timeZoneName");
    return part ? part.value : meta.tz;
  }
  function ago(ms) {
    const min = Math.max(0, Math.round((Date.now() - ms) / 60000));
    if (min < 1) return "just now";
    if (min < 60) return min + " min ago";
    const h = Math.floor(min / 60);
    return h + " h " + (min % 60) + " min ago";
  }
  const pct = (n, total) => (total ? (100 * n / total).toFixed(1) + "%" : "-");
  function sameDay(a, b) {
    return fmt(a, { year: "numeric", month: "2-digit", day: "2-digit" }) === fmt(b, { year: "numeric", month: "2-digit", day: "2-digit" });
  }
  function parseCSV(text) {
    const lines = text.trim().split(/\r?\n/);
    if (lines.length < 2) return [];
    const head = lines[0].split(",");
    return lines.slice(1).map((line) => {
      const v = line.split(",");
      const o = {};
      head.forEach((h, i) => { o[h] = v[i]; });
      o.n = +o.n;
      return o;
    });
  }

  // ---------- data ----------
  async function load() {
    const t = "?t=" + Date.now();
    try {
      const [m, csv] = await Promise.all([
        fetch(DATA + "meta.json" + t, { cache: "no-store" }).then((r) => { if (!r.ok) throw new Error("meta.json " + r.status); return r.json(); }),
        fetch(DATA + "status_bins.csv" + t, { cache: "no-store" }).then((r) => { if (!r.ok) throw new Error("status_bins.csv " + r.status); return r.text(); }),
      ]);
      meta = m;
      rows = parseCSV(csv);
    } catch (e) {
      $("sub").textContent = "Could not load the data (" + e.message + "). Try Refresh.";
      return;
    }
    launchMs = Date.parse(meta.launch_utc);
    binMs = meta.bin_minutes * 60000;
    const pulledMs = Date.parse(meta.pulled_at);
    let last = pulledMs;
    rows.forEach((r) => { r.idx = Math.round((Date.parse(r.bin_start) - launchMs) / binMs); last = Math.max(last, launchMs + (r.idx + 1) * binMs); });
    nBins = Math.max(0, Math.ceil((last - launchMs) / binMs));
    setupRange();
    renderAll();
  }

  // ---------- controls ----------
  function setupCountries() {
    const box = $("country");
    box.innerHTML = "";
    ["All"].concat(Object.keys(meta.countries)).forEach((c) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = c;
      b.setAttribute("aria-pressed", String(c === state.country));
      b.addEventListener("click", () => { state.country = c; store("pfs.country", c); setupCountries(); renderCharts(); });
      box.appendChild(b);
    });
    if (state.country !== "All" && !(state.country in meta.countries)) { state.country = "All"; setupCountries(); }
  }

  function setupRange() {
    const from = $("from"), to = $("to");
    from.max = to.max = String(nBins);
    if (state.toAtEnd || state.to > nBins) state.to = nBins;
    if (state.from >= state.to) state.from = Math.max(0, state.to - 1);
    from.value = state.from;
    to.value = state.to;
    $("range").style.display = nBins > 0 ? "" : "none";
  }

  function onRange(which) {
    let f = +$("from").value, t = +$("to").value;
    if (f >= t) {
      if (which === "from") f = Math.max(0, t - 1); else t = Math.min(nBins, f + 1);
    }
    state.from = f; state.to = t; state.toAtEnd = t === nBins;
    $("from").value = f; $("to").value = t;
    renderCharts();
  }

  function setupRefresh() {
    const auto = $("auto");
    const saved = store("pfs.auto");
    auto.checked = saved === null ? true : saved === "1";
    auto.addEventListener("change", () => { store("pfs.auto", auto.checked ? "1" : "0"); schedule(); });
    $("refresh").addEventListener("click", load);
    $("from").addEventListener("input", () => onRange("from"));
    $("to").addEventListener("input", () => onRange("to"));
  }

  function schedule() {
    if (timer) clearInterval(timer);
    timer = null;
    const min = meta ? meta.refresh_min : 2;
    $("refresh-min").textContent = String(min);
    if ($("auto").checked) timer = setInterval(load, min * 60000);
  }

  // ---------- header and info ----------
  function renderHeader() {
    const pulledMs = Date.parse(meta.pulled_at);
    $("sub").textContent = "Participants counted from launch, " + fmtDayHM(launchMs) + " " + zoneName(launchMs) +
      ". Times are shown in " + meta.tz + ".";
    const parts = Object.entries(meta.countries).map(([c, info]) => {
      if (info.status === "ok") return "<span>" + esc(c) + ": pulled " + esc(fmtHM(Date.parse(info.as_of))) + " (" + ago(Date.parse(info.as_of)) + ")</span>";
      if (info.as_of) return '<span class="failed">' + esc(c) + ": last pull failed, data as of " + esc(fmtHM(Date.parse(info.as_of))) + " (" + ago(Date.parse(info.as_of)) + ")</span>";
      return '<span class="failed">' + esc(c) + ": no data yet (server not reached)</span>";
    });
    $("pulls").innerHTML = "Last pull " + esc(fmtDayHM(pulledMs)) + " (" + ago(pulledMs) + "). " + parts.join(" ");
    const stale = meta.stale_after_min && (Date.now() - pulledMs) / 60000 > meta.stale_after_min;
    $("warn").innerHTML = stale ? '<div class="warn" role="status">The data is older than ' + meta.stale_after_min + " minutes; updates may have stopped.</div>" : "";
    renderInfo();
    $("footer").innerHTML = "Aggregate counts only; no individual data is published. Scripts: <a href=\"" + esc(meta.scripts_url) + "\">" +
      esc(meta.scripts_url.replace(/^https?:\/\//, "")) + "</a>" + (meta.code_version ? " (version " + esc(meta.code_version) + ")" : "") + ".";
  }

  function renderInfo() {
    const ignore = meta.ignore_codes.length ? meta.ignore_codes.join(", ") : "none";
    const items = [
      "<b>Who is counted:</b> every participant whose session was created on or after " + esc(fmtDayHM(launchMs)) + " (" + esc(meta.tz) + "), per country server. One participant is one row in the study database.",
      "<b>Time window:</b> the sliders select participants by the time their session was created, in steps of " + meta.bin_minutes + " minutes. Counts are the status of those participants at the last pull (shown at the top). A participant's status can still change after they are counted, for example after a restart.",
      "<b>done:</b> reached the end page through the study timer.",
      "<b>cancelled:</b> the session was stopped by the study software. There is no cancel button for participants; a session is stopped when an automated browser is detected (bot), when the participant did not focus on the feed or view enough posts by the end (idle: under " + meta.idle_min_seconds + " s focused or under " + meta.idle_min_posts + " posts viewed), or when the timeline page was reloaded (reload). other means stopped without one of these three reasons.",
      "<b>Several codes:</b> a participant can be stopped, restart (allowed after bot or idle detection) and be stopped again. The reason shown is the last stop. Each participant is counted once, so the shares add up to 100%.",
      "<b>incomplete:</b> neither done nor stopped. These participants left before the end or are still in their session (sessions last up to about 10 minutes). possibly in session marks those who started less than " + meta.session_min + " minutes before the last pull. error logged means at least one technical error was recorded (ignoring " + esc(ignore) + ").",
      "<b>Data and code:</b> aggregate counts only; no individual data is published. Scripts: <a href=\"" + esc(meta.scripts_url) + "\">" + esc(meta.scripts_url.replace(/^https?:\/\//, "")) + "</a>" + (meta.code_version ? " (version " + esc(meta.code_version) + ")" : "") + ".",
    ];
    $("info-body").innerHTML = "<ul>" + items.map((t) => "<li>" + t + "</li>").join("") + "</ul>";
  }

  // ---------- selection ----------
  function selection() {
    const perBin = new Array(Math.max(0, state.to - state.from)).fill(0);
    const cat = {};
    let total = 0;
    rows.forEach((r) => {
      if (state.country !== "All" && r.country !== state.country) return;
      if (r.idx < state.from || r.idx >= state.to) return;
      perBin[r.idx - state.from] += r.n;
      const k = r.status + "|" + r.reason;
      cat[k] = (cat[k] || 0) + r.n;
      total += r.n;
    });
    return { perBin, cat, total };
  }

  function renderCharts() {
    if (!meta) return;
    $("from-out").textContent = nBins ? fmtDayHM(launchMs + state.from * binMs) : "";
    $("to-out").textContent = nBins ? fmtDayHM(launchMs + state.to * binMs) : "";
    const who = state.country === "All" ? "all countries" : state.country;
    $("c1-title").textContent = "Participants since launch, " + who;
    if (nBins === 0) {
      empty("c1", "No participants yet. Launch: " + fmtDayHM(launchMs) + " " + zoneName(launchMs) + ".");
      empty("c2", "No participants yet.");
      $("legend2").innerHTML = ""; $("table2").innerHTML = "";
      $("c1-note").textContent = ""; $("c2-note").textContent = "";
      return;
    }
    const sel = selection();
    const range = fmtDayHM(launchMs + state.from * binMs) + " to " + fmtDayHM(launchMs + state.to * binMs);
    $("c1-note").textContent = "Cumulative number of participants by session start time, " + range + ".";
    $("c2-note").textContent = sel.total + " participants who started " + range + " (" + who + "), status at the last pull.";
    if (sel.total === 0) {
      const msg = state.country !== "All" && !rows.some((r) => r.country === state.country)
        ? "No participants yet for " + state.country + "." : "No participants in this time range.";
      empty("c1", msg); empty("c2", msg);
      $("legend2").innerHTML = ""; $("table2").innerHTML = "";
      return;
    }
    drawCumulative(sel);
    drawShareBar(sel);
    drawTable(sel);
  }

  function empty(id, text) {
    const box = $(id);
    [...box.querySelectorAll("svg, .empty")].forEach((n) => n.remove());
    const d = document.createElement("div");
    d.className = "empty";
    d.textContent = text;
    box.appendChild(d);
  }

  function clear(id) {
    const box = $(id);
    [...box.querySelectorAll("svg, .empty")].forEach((n) => n.remove());
    return box;
  }

  // integer y axis with at most 5 steps of 1, 2 or 5 x 10^k
  function yAxis(maxV) {
    for (let p = 1; ; p *= 10) {
      for (const s of [1, 2, 5]) {
        const step = s * p;
        if (Math.ceil(maxV / step) <= 5) return { step, max: Math.max(step, Math.ceil(maxV / step) * step) };
      }
    }
  }

  // ---------- chart 1: cumulative participants ----------
  function drawCumulative(sel) {
    const box = clear("c1");
    const W = Math.max(300, box.clientWidth), H = 220;
    const m = { l: 40, r: 14, t: 10, b: 28 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const nb = sel.perBin.length;
    const cum = [0];
    sel.perBin.forEach((n) => cum.push(cum[cum.length - 1] + n));
    const ya = yAxis(cum[cum.length - 1]);
    const ymax = ya.max;
    const x = (k) => m.l + (nb ? (k / nb) * iw : 0);
    const y = (v) => m.t + ih - (v / ymax) * ih;
    const t0 = launchMs + state.from * binMs;
    const svg = el("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "Cumulative participants over time" }, null);
    box.insertBefore(svg, box.firstChild);

    // y grid and labels
    for (let v = 0; v <= ymax; v += ya.step) {
      el("line", { x1: m.l, x2: m.l + iw, y1: y(v), y2: y(v), stroke: css("--grid"), "stroke-width": 1 }, svg);
      el("text", { x: m.l - 6, y: y(v) + 4, "text-anchor": "end" }, svg).textContent = v;
    }
    // x ticks: about one per 90 px, on whole bins
    const every = Math.max(1, Math.ceil(nb / Math.max(1, Math.floor(iw / 90))));
    const multiDay = !sameDay(t0, t0 + nb * binMs);
    for (let k = 0; k <= nb; k += every) {
      const ms = t0 + k * binMs;
      el("line", { x1: x(k), x2: x(k), y1: m.t + ih, y2: m.t + ih + 4, stroke: css("--border") }, svg);
      el("text", { x: x(k), y: H - 8, "text-anchor": k === 0 ? "start" : (k === nb ? "end" : "middle") }, svg).textContent = multiDay ? fmt(ms, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : fmtHM(ms);
    }
    el("line", { x1: m.l, x2: m.l + iw, y1: m.t + ih, y2: m.t + ih, stroke: css("--border") }, svg);

    const d = cum.map((v, k) => (k ? "L" : "M") + x(k).toFixed(1) + "," + y(v).toFixed(1)).join("");
    el("path", { d, fill: "none", stroke: css("--accent"), "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
    const endDot = el("circle", { cx: x(nb), cy: y(cum[nb]), r: 4, fill: css("--accent"), stroke: css("--surface-1"), "stroke-width": 2 }, svg);
    el("text", { x: Math.min(x(nb), m.l + iw) - 8, y: y(cum[nb]) - 8, "text-anchor": "end", style: "fill:" + css("--text-primary") + ";font-weight:600" }, svg).textContent = cum[nb];

    // hover: crosshair + tooltip
    const guide = el("line", { y1: m.t, y2: m.t + ih, stroke: css("--text-muted"), "stroke-dasharray": "3 3", visibility: "hidden" }, svg);
    const dot = el("circle", { r: 5, fill: css("--accent"), stroke: css("--surface-1"), "stroke-width": 2, visibility: "hidden" }, svg);
    const hit = el("rect", { x: m.l, y: m.t, width: iw, height: ih, fill: "transparent" }, svg);
    const tip = $("tip1");
    function move(ev) {
      const r = svg.getBoundingClientRect();
      const px = ((ev.clientX - r.left) / r.width) * W;
      const k = Math.max(0, Math.min(nb, Math.round(((px - m.l) / iw) * nb)));
      guide.setAttribute("x1", x(k)); guide.setAttribute("x2", x(k)); guide.setAttribute("visibility", "visible");
      dot.setAttribute("cx", x(k)); dot.setAttribute("cy", y(cum[k])); dot.setAttribute("visibility", "visible");
      endDot.setAttribute("visibility", k === nb ? "hidden" : "visible");
      const ms = t0 + k * binMs;
      const added = k ? sel.perBin[k - 1] : 0;
      tip.innerHTML = "<b>" + cum[k] + "</b> participants by " + esc(fmtHM(ms)) +
        (k ? '<br><span class="muted">+' + added + " from " + esc(fmtHM(ms - binMs)) + " to " + esc(fmtHM(ms)) + "</span>" : "");
      tip.style.display = "block";
      const sx = (x(k) / W) * r.width, sy = (y(cum[k]) / H) * r.height;
      const left = sx + 12 + tip.offsetWidth > r.width ? sx - 12 - tip.offsetWidth : sx + 12;
      tip.style.left = left + "px"; tip.style.top = Math.max(0, sy - tip.offsetHeight - 8) + "px";
    }
    function leave() {
      guide.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden");
      endDot.setAttribute("visibility", "visible"); tip.style.display = "none";
    }
    hit.addEventListener("pointermove", move);
    hit.addEventListener("pointerdown", move);
    hit.addEventListener("pointerleave", leave);
  }

  // ---------- chart 2: share bar + table ----------
  function statusTotals(sel) {
    const t = {};
    STATUSES.forEach((s) => { t[s] = 0; });
    Object.entries(sel.cat).forEach(([k, n]) => { t[k.split("|")[0]] += n; });
    return t;
  }

  function drawShareBar(sel) {
    const box = clear("c2");
    const W = Math.max(300, box.clientWidth), H = 34, gap = 2;
    const svg = el("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "Share of participants by status" }, null);
    box.insertBefore(svg, box.firstChild);
    const clip = el("clipPath", { id: "barclip" }, el("defs", {}, svg));
    el("rect", { x: 0, y: 0, width: W, height: H, rx: 4 }, clip);
    const g = el("g", { "clip-path": "url(#barclip)" }, svg);
    const tot = statusTotals(sel);
    const tip = $("tip2");
    let x0 = 0;
    const present = STATUSES.filter((s) => tot[s] > 0);
    present.forEach((s, i) => {
      const w = (tot[s] / sel.total) * W;
      const wDraw = Math.max(0, w - (i < present.length - 1 ? gap : 0));
      const rect = el("rect", { x: x0, y: 0, width: wDraw, height: H, fill: css(STATUS_VAR[s]) }, g);
      const label = LABEL[s] + " " + pct(tot[s], sel.total);
      if (wDraw > label.length * 7 + 12) {
        el("text", { x: x0 + 8, y: H / 2 + 4, style: "fill:#0b0b0b;font-weight:600;pointer-events:none" }, svg).textContent = label;
      }
      const show = (ev) => {
        tip.innerHTML = "<b>" + esc(LABEL[s]) + "</b>: " + tot[s] + " (" + pct(tot[s], sel.total) + ")";
        tip.style.display = "block";
        const r = svg.getBoundingClientRect();
        const sx = ev.clientX - r.left;
        tip.style.left = Math.min(Math.max(0, sx - tip.offsetWidth / 2), r.width - tip.offsetWidth) + "px";
        tip.style.top = (H / W) * r.width + 6 + "px";
      };
      rect.addEventListener("pointermove", show);
      rect.addEventListener("pointerdown", show);
      rect.addEventListener("pointerleave", () => { tip.style.display = "none"; });
      x0 += w;
    });
    $("legend2").innerHTML = STATUSES.map((s) => '<span><span class="sw" style="background:var(' + STATUS_VAR[s] + ')"></span>' + LABEL[s] + "</span>").join("");
  }

  function drawTable(sel) {
    const tot = statusTotals(sel);
    const reasons = {};
    meta.categories.forEach((c) => { (reasons[c.status] = reasons[c.status] || []).push(c.reason); });
    const maxShare = Math.max(...STATUSES.map((s) => tot[s] / sel.total));
    const bar = (n, s) => '<div class="minibar" style="width:' + ((n / sel.total) / (maxShare || 1) * 100).toFixed(1) + "%;background:var(" + STATUS_VAR[s] + ')"></div>';
    let html = '<table><thead><tr><th>Status</th><th class="num">n</th><th class="num">share</th><th class="bar-cell"><span class="sr">share bar</span></th></tr></thead><tbody>';
    STATUSES.forEach((s) => {
      html += '<tr class="group"><td><span class="sw" style="background:var(' + STATUS_VAR[s] + ')"></span>' + LABEL[s] + '</td><td class="num">' + tot[s] +
        '</td><td class="num">' + pct(tot[s], sel.total) + '</td><td class="bar-cell">' + bar(tot[s], s) + "</td></tr>";
      if (s === "done") return;
      (reasons[s] || []).forEach((r) => {
        const n = sel.cat[s + "|" + r] || 0;
        html += '<tr class="sub"><td>' + esc(LABEL[r] || r) + '</td><td class="num">' + n + '</td><td class="num">' + pct(n, sel.total) +
          '</td><td class="bar-cell">' + bar(n, s) + "</td></tr>";
      });
    });
    html += '<tr class="total"><td>total</td><td class="num">' + sel.total + '</td><td class="num">100%</td><td class="bar-cell"></td></tr></tbody></table>';
    $("table2").innerHTML = html;
  }

  function renderAll() {
    setupCountries();
    renderHeader();
    schedule();
    renderCharts();
  }

  // ---------- start ----------
  setupRefresh();
  let resizeT = null;
  window.addEventListener("resize", () => { clearTimeout(resizeT); resizeT = setTimeout(renderCharts, 150); });
  // keep "x min ago" current between refreshes
  setInterval(() => { if (meta) renderHeader(); }, 60000);
  const mq = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  if (mq && mq.addEventListener) mq.addEventListener("change", renderCharts);
  load();
})();

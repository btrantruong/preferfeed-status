/* Small helpers shared by the modules: DOM, formatting, storage. No chart code. */
export const SVGNS = "http://www.w3.org/2000/svg";

export const $ = (id) => document.getElementById(id);

export function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch (e) { return null; }
  return null;
}

export function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

export function css(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** DOM element with attributes and children (strings become text nodes). */
export function h(tag, attrs, ...kids) {
  const node = document.createElement(tag);
  for (const k in attrs || {}) {
    if (k === "class") node.className = attrs[k];
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), attrs[k]);
    else node.setAttribute(k, attrs[k]);
  }
  kids.flat().forEach((c) => { if (c != null) node.append(c.nodeType ? c : document.createTextNode(String(c))); });
  return node;
}

/** Formatters for a time zone: fmt(ms, options), fmtHM, fmtDayHM, zoneName. */
export function makeFormatters(tz) {
  const fmt = (ms, opts) => new Intl.DateTimeFormat("en-GB", Object.assign({ timeZone: tz, hourCycle: "h23" }, opts)).format(new Date(ms));
  return {
    fmt,
    fmtHM: (ms) => fmt(ms, { hour: "2-digit", minute: "2-digit" }),
    fmtDayHM: (ms) => fmt(ms, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }),
    fmtDay: (ms) => fmt(ms, { day: "numeric", month: "short" }),
    zoneName: (ms) => {
      const part = new Intl.DateTimeFormat("en-GB", { timeZone: tz, timeZoneName: "short" }).formatToParts(new Date(ms)).find((p) => p.type === "timeZoneName");
      return part ? part.value : tz;
    },
    sameDay: (a, b) => fmt(a, { year: "numeric", month: "2-digit", day: "2-digit" }) === fmt(b, { year: "numeric", month: "2-digit", day: "2-digit" }),
  };
}

export function ago(ms) {
  const min = Math.max(0, Math.round((Date.now() - ms) / 60000));
  if (min < 1) return "just now";
  if (min < 60) return min + " min ago";
  const hh = Math.floor(min / 60);
  return hh + " h " + (min % 60) + " min ago";
}

export const pct = (n, total) => (total ? (100 * n / total).toFixed(1) + "%" : "-");
export const pct0 = (n, total) => (total ? Math.round(100 * n / total) + "%" : "-");

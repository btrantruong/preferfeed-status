/* The post card of the trajectory panels: opens on hover or focus of a batch dot, stays on click, closes with Escape or a click
   elsewhere. Post text is untrusted: it is inserted with textContent, never as HTML. */
import { h } from "./util.js";

let card = null, pinned = false, owner = null;

export function closeCard() { if (card) { card.remove(); card = null; pinned = false; owner = null; } }
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeCard(); });
document.addEventListener("pointerdown", (e) => { if (card && pinned && !card.contains(e.target)) closeCard(); });

/** Position next to (x, y) in the viewport, inside it; at phone width the CSS makes it a bottom sheet. */
function place(el, x, y) {
  const w = el.offsetWidth, hgt = el.offsetHeight;
  el.style.left = Math.max(8, Math.min(x + 14, window.innerWidth - w - 8)) + "px";
  el.style.top = Math.max(8, Math.min(y - 10, window.innerHeight - hgt - 8)) + "px";
}

/** content: {title, lines:[string], posts:[{head, vec, text}], warn} -> card element */
function build(content) {
  const el = h("div", { class: "postcard", role: "dialog", "aria-label": content.title },
    h("div", { class: "hd" }, h("b", {}, content.title), h("span", {}, content.sub || "")));
  (content.lines || []).forEach((l) => el.append(h("div", { class: "vec" }, l)));
  if (content.warn) el.append(h("div", { class: "warn cov" }, content.warn));
  (content.posts || []).forEach((p) => el.append(h("div", { class: "post" }, h("div", { class: "vec" }, p.head), h("div", { class: "txt" }, p.text))));
  return el;
}

/** Bind a shape: hover and focus open, click pins. getContent() is called when it opens. */
export function bindCard(node, getContent) {
  const open = (ev, pin) => {
    if (pinned && owner !== node) return;
    const first = !card || owner !== node;
    if (first) { closeCard(); card = build(getContent()); document.body.append(card); owner = node; }
    const r = node.getBoundingClientRect();
    place(card, ev && ev.clientX ? ev.clientX : r.right, ev && ev.clientY ? ev.clientY : r.top);
    if (pin) pinned = true;
  };
  node.setAttribute("tabindex", "0");
  node.addEventListener("pointerenter", (e) => { if (e.pointerType !== "touch") open(e, false); });
  node.addEventListener("pointerleave", () => { if (!pinned) closeCard(); });
  node.addEventListener("focus", (e) => open(null, false));
  node.addEventListener("blur", () => { if (!pinned) closeCard(); });
  node.addEventListener("click", (e) => { e.stopPropagation(); if (pinned && owner === node) { closeCard(); } else { pinned = false; closeCard(); open(e, true); } });
  node.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pinned = false; closeCard(); open(null, true); } });
}

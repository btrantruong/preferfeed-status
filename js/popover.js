/* Info icon with an explanation: opens on hover, focus and click; closes on Escape, a click elsewhere or leave. */
import { h } from "./util.js";

let open = null;
function close() { if (open) { open.pop.remove(); open.btn.setAttribute("aria-expanded", "false"); open = null; } }
document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
document.addEventListener("pointerdown", (e) => { if (open && !open.pop.contains(e.target) && e.target !== open.btn) close(); });

export function infoButton(label, text) {
  const btn = h("button", { type: "button", class: "ibtn", "aria-label": "About " + label, "aria-expanded": "false" }, "i");
  const show = () => {
    if (open && open.btn === btn) return;
    close();
    const pop = h("div", { class: "pop", role: "tooltip" }, text);
    document.body.append(pop);
    const r = btn.getBoundingClientRect(), pw = pop.offsetWidth, ph = pop.offsetHeight;
    pop.style.left = Math.max(8, Math.min(r.left, window.innerWidth - pw - 8)) + "px";
    pop.style.top = (r.bottom + ph + 12 > window.innerHeight ? Math.max(8, r.top - ph - 6) : r.bottom + 6) + "px";
    btn.setAttribute("aria-expanded", "true");
    open = { pop, btn };
  };
  btn.addEventListener("mouseenter", show);
  btn.addEventListener("focus", show);
  btn.addEventListener("click", (e) => { e.stopPropagation(); open && open.btn === btn && e.detail ? close() : show(); });
  btn.addEventListener("mouseleave", () => { setTimeout(() => { if (open && open.btn === btn && !btn.matches(":focus")) close(); }, 150); });
  btn.addEventListener("blur", () => setTimeout(() => { if (open && open.btn === btn) close(); }, 100));
  return btn;
}

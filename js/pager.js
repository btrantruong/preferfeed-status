/* Pager of one panel: previous, next, "k of N", one dot per page. Pure index logic is exported for tests. */
import { h } from "./util.js";

export const clampPage = (k, n) => Math.min(Math.max(0, k | 0), Math.max(0, n - 1));

/** Build the pager controls into `root`; onPage(k) is called after a change. Returns {set(k, titles)}. */
export function createPager(root, o) {
  const prev = h("button", { type: "button", "aria-label": "Previous page" }, "‹ Previous");
  const next = h("button", { type: "button", "aria-label": "Next page" }, "Next ›");
  const count = h("span", { "aria-live": "polite" });
  const dots = h("span", { class: "dots", role: "group", "aria-label": "Pages" });
  root.append(prev, count, next, dots);
  let k = 0, titles = [];
  const go = (j) => { const t = clampPage(j, titles.length); if (t !== k) { k = t; paint(); o.onPage(k); } };
  prev.addEventListener("click", () => go(k - 1));
  next.addEventListener("click", () => go(k + 1));
  function paint() {
    count.textContent = (k + 1) + " of " + titles.length;
    prev.disabled = k === 0; next.disabled = k >= titles.length - 1;
    dots.replaceChildren(...titles.map((t, j) => {
      const d = h("button", { type: "button", class: "dot", "aria-label": "Page " + (j + 1) + ": " + t, title: t, "aria-current": String(j === k) });
      d.addEventListener("click", () => go(j));
      return d;
    }));
  }
  return { set(page, list) { titles = list; k = clampPage(page, list.length); paint(); return k; }, get: () => k };
}

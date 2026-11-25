/* Two-handle range slider on one track: from and to, in whole steps. The arithmetic is pure (tested with
   node --test); createSlider adds the DOM: pointer events (mouse, touch, pen) and the keyboard. */

export const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/** Step nearest to a pointer position: x and left are page pixels, width the track width, max the last step. */
export function valueFromX(x, left, width, max) {
  if (width <= 0 || max <= 0) return 0;
  return clamp(Math.round(((x - left) / width) * max), 0, max);
}

/** Move one handle to value v, keeping from < to by at least minGap steps. Returns {from, to}. */
export function moveHandle(vals, which, v, max, minGap) {
  let { from, to } = vals;
  if (which === "from") from = clamp(v, 0, to - minGap);
  else to = clamp(v, from + minGap, max);
  return { from, to };
}

/** Key to step change: arrows one step, Page keys pageStep steps (an hour), Home and End to the ends; null otherwise. */
export function keyStep(key, current, max, pageStep) {
  switch (key) {
    case "ArrowLeft": case "ArrowDown": return current - 1;
    case "ArrowRight": case "ArrowUp": return current + 1;
    case "PageDown": return current - pageStep;
    case "PageUp": return current + pageStep;
    case "Home": return 0;
    case "End": return max;
    default: return null;
  }
}

/** Build the slider inside `root`. opts: {max, from, to, minGap, pageStep, label(which, value), onChange(vals)}.
    Returns {set(max, from, to), get()}. */
export function createSlider(root, opts) {
  const state = { max: opts.max || 0, from: opts.from || 0, to: opts.to || 0 };
  const track = document.createElement("div"); track.className = "track2";
  const band = document.createElement("div"); band.className = "band2";
  track.append(band);
  const thumbs = {};
  ["from", "to"].forEach((which) => {
    const t = document.createElement("div");
    t.className = "thumb2"; t.tabIndex = 0; t.setAttribute("role", "slider");
    t.setAttribute("aria-label", which === "from" ? "Window start" : "Window end");
    t.setAttribute("aria-orientation", "horizontal");
    thumbs[which] = t; track.append(t);
  });
  root.append(track);

  function paint() {
    const pctOf = (v) => (state.max ? (100 * v) / state.max : 0);
    thumbs.from.style.left = pctOf(state.from) + "%";
    thumbs.to.style.left = pctOf(state.to) + "%";
    band.style.left = pctOf(state.from) + "%";
    band.style.width = pctOf(state.to - state.from) + "%";
    ["from", "to"].forEach((w) => {
      const t = thumbs[w];
      t.setAttribute("aria-valuemin", w === "from" ? 0 : state.from + (opts.minGap || 1));
      t.setAttribute("aria-valuemax", w === "from" ? state.to - (opts.minGap || 1) : state.max);
      t.setAttribute("aria-valuenow", state[w]);
      t.setAttribute("aria-valuetext", opts.label(w, state[w]));
    });
  }
  function apply(which, v, fire) {
    const next = moveHandle(state, which, v, state.max, opts.minGap || 1);
    if (next.from === state.from && next.to === state.to) return;
    Object.assign(state, next); paint();
    if (fire !== false) opts.onChange({ from: state.from, to: state.to, which });
  }
  ["from", "to"].forEach((which) => {
    const t = thumbs[which];
    t.addEventListener("pointerdown", (ev) => {
      ev.preventDefault(); t.setPointerCapture(ev.pointerId); t.focus(); t.classList.add("drag");
    });
    t.addEventListener("pointermove", (ev) => {
      if (!t.hasPointerCapture(ev.pointerId)) return;
      const r = track.getBoundingClientRect();
      apply(which, valueFromX(ev.clientX, r.left, r.width, state.max));
    });
    const end = (ev) => { t.classList.remove("drag"); if (t.hasPointerCapture(ev.pointerId)) t.releasePointerCapture(ev.pointerId); };
    t.addEventListener("pointerup", end); t.addEventListener("pointercancel", end);
    t.addEventListener("keydown", (ev) => {
      const v = keyStep(ev.key, state[which], state.max, opts.pageStep || 4);
      if (v === null) return;
      ev.preventDefault(); apply(which, v);
    });
  });
  // a click on the track moves the nearer handle
  track.addEventListener("pointerdown", (ev) => {
    if (ev.target !== track && ev.target !== band) return;
    const r = track.getBoundingClientRect();
    const v = valueFromX(ev.clientX, r.left, r.width, state.max);
    apply(Math.abs(v - state.from) <= Math.abs(v - state.to) ? "from" : "to", v);
  });
  paint();
  return {
    set(max, from, to) { state.max = max; state.from = from; state.to = to; paint(); },
    get() { return { from: state.from, to: state.to, max: state.max }; },
    focusable: thumbs,
  };
}

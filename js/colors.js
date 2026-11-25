/* Color roles as CSS custom properties of index.html (light and dark values are defined there). */
export const STATUS = { done: "--s-done", cancelled: "--s-cancelled", incomplete: "--s-incomplete" };
export const STATUS_LABEL = { done: "done", cancelled: "cancelled", incomplete: "incomplete" };
export const CONDITIONS = ["RANDOM", "ATTENTION", "PREFERENCE"];
export const COND = { ATTENTION: "--c7", PREFERENCE: "--c5", RANDOM: "--c6", unknown: "--text-muted" };
export const COUNTRY_SLOTS = ["--c1", "--c2", "--c3", "--c4"];
export const FLOW = { SERVER_ERROR: "--c1", NOT_FOUND: "--c2", DUPLICATE_PARTICIPATION_ATTEMPT: "--c3",
  PAGE_RELOAD_DETECTED: "--c4", IDLE_DETECTED: "--c5", "client failure": "--c6", AUTOMATED_BROWSER_DETECTED: "--c7",
  TIMELINE_RESTARTED: "--c8", other: "--text-muted", END: "--border", START: "--border" };
export const DIMS = ["us_v_them", "fear", "outrage", "pride", "hope"];
export const DIM_VARS = ["--c1", "--c2", "--c3", "--c4", "--c5"];
export const lc = (s) => String(s).toLowerCase();

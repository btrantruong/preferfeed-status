/* Which charts sit in which panel, in which order. Each chart module exports id, title, group (optional),
   files, window ("created" or "event"), caption(meta), how, draw(box, c). */
import top from "./charts/top.js";
import cs0 from "./charts/cs0.js";
import cs1 from "./charts/cs1.js";
import cs2 from "./charts/cs2.js";
import dc1 from "./charts/dc1.js";
import dc2 from "./charts/dc2.js";
import dc3 from "./charts/dc3.js";
import se1 from "./charts/se1.js";
import se2 from "./charts/se2.js";
import se3 from "./charts/se3.js";
import se4 from "./charts/se4.js";
import se5 from "./charts/se5.js";
import ap1 from "./charts/ap1.js";
import ap2 from "./charts/ap2.js";
import sp1 from "./charts/sp1.js";
import sp2 from "./charts/sp2.js";

export const TOP = top;
export const PANELS = [
  { id: "A", title: "Completion status", pages: [cs0, cs1, cs2] },
  { id: "B", title: "Data completeness and errors", pages: [dc3, dc2, se1, se2, se3, se4, se5, dc1] },
  { id: "C", title: "Algorithm check", pages: [ap1, ap2] },
  { id: "D", title: "User spot check (local preview only)", pages: [sp2, sp1], local: true },
];

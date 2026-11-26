/* Panel A categories: labels, order, colors, the rows of the outcome table and the stacks of the retry plots.
   Pure, tested with node --test. The categories are those of pipeline/outcomes.py. */

export const ERROR_TYPES = ["idle", "reload", "bot", "server", "client", "other"];
export const TYPE_LABEL = { idle: "idle", reload: "reload", bot: "bot", server: "server error", client: "client failure", other: "other" };
export const GROUPS = [
  { key: "done", label: "done", color: "--s-done" },
  { key: "in_session", label: "still in session", color: "--c3" },
  { key: "left", label: "left session", color: "--text-muted" },
];
const DONE = [["done_first", "first try"], ["done_retry", "after retry"]];
const LEFT = [["left_no_error", "no error, no retry"], ["left_no_error_retried", "no error, retried"],
  ["left_error_no_retry", "error, no retry"], ["left_retried_after_error", "retried after error"]];
const WITH_ERROR = ["left_error_no_retry", "left_retried_after_error"];
export const RETRY_OUTCOMES = [
  { key: "done", label: "done", color: "--s-done" },
  { key: "in_session", label: "still in session", color: "--c3" },
  { key: "left_final_error", label: "left, error in the last attempt", color: "--c2" },
  { key: "left_no_final_error", label: "left, no error in the last attempt", color: "--text-muted" },
];

/** rows: [{outcome, last_error, n}] -> {total, groups: {done, in_session, left}, table: [{level, label, n, color}]}.
    The error types under the two error categories are listed only when they have participants. */
export function outcomeTree(rows) {
  const sum = (pred) => rows.filter(pred).reduce((a, r) => a + r.n, 0);
  const of = (key) => sum((r) => r.outcome === key);
  const [done, session, left] = GROUPS;
  const groups = {
    done: DONE.reduce((a, [k]) => a + of(k), 0),
    in_session: of("in_session"),
    left: LEFT.reduce((a, [k]) => a + of(k), 0),
  };
  const table = [{ level: 0, label: done.label, n: groups.done, color: done.color }];
  DONE.forEach(([k, label]) => table.push({ level: 1, label, n: of(k), color: done.color }));
  table.push({ level: 0, label: "incomplete", n: groups.in_session + groups.left, color: null });
  table.push({ level: 1, label: session.label, n: groups.in_session, color: session.color });
  table.push({ level: 1, label: left.label, n: groups.left, color: left.color });
  LEFT.forEach(([k, label]) => {
    table.push({ level: 2, label, n: of(k), color: left.color });
    if (!WITH_ERROR.includes(k)) return;
    const seen = rows.filter((r) => r.outcome === k).map((r) => r.last_error);
    const types = ERROR_TYPES.concat(seen.filter((t) => !ERROR_TYPES.includes(t))).filter((t, i, a) => a.indexOf(t) === i);
    types.forEach((t) => {
      const n = sum((r) => r.outcome === k && r.last_error === t);
      if (n) table.push({ level: 3, label: "last error: " + (TYPE_LABEL[t] || t), n, color: left.color });
    });
  });
  return { total: sum(() => true), groups, table };
}

/** Participants per x value and retry outcome. rows: retries.csv rows; field: "trigger" or "retries"; xs: values. */
export function retryStacks(rows, field, xs) {
  return RETRY_OUTCOMES.map((o) => ({ name: o.label, color: o.color,
    values: xs.map((x) => rows.filter((r) => r[field] === x && r.retry_outcome === o.key).reduce((a, r) => a + r.n, 0)) }));
}

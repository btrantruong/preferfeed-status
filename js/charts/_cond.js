/* Condition shown by a figure that draws one condition at a time (pure, tested with node --test). */

/** The stored choice if it has data in the selection, else the first condition that has (null if none has).
    present: conditions with data, in display order. */
export function pickCondition(present, stored) {
  return present.includes(stored) ? stored : present[0] || null;
}

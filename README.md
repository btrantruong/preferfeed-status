# preferFeed fielding status

Page: https://btrantruong.github.io/preferfeed-status/

The page shows, per country server or for all countries, how many participants started the study since the launch and the status of each at the last data pull. Only aggregate counts are published; no individual data leaves the study machines.

## Status definitions

One participant is one row of the study's `visited_users` table with `created_at` on or after the launch. Each participant gets exactly one category at the time of the pull, so the shares add up to 100%.

- done: `done` is true (the participant reached the end page through the study timer).
- cancelled: `cancelled` is true and `done` is not. The reason is the last stopping code in the participant's error log, ordered by server time: bot (automated browser detected), idle (too little focus time or too few posts viewed), reload (timeline page reloaded), or other (no stopping code). A participant can restart after bot or idle detection, so the last stop is the one shown.
- incomplete: neither flag is set. possibly in session: created less than `session_min` minutes before the pull, so the status is not final. error logged: at least one logged error code outside `ignore_codes`. no error: the rest.

The thresholds and codes used for a given pull are in `data/meta.json`.

## Data files

- `data/status_bins.csv`: `bin_start` (UTC, ISO 8601), `country`, `status`, `reason`, `n`. Bins are `bin_minutes` wide and start at the launch; only non-zero cells are listed. Each pull recomputes all participants since the launch from the current database state.
- `data/meta.json`: pull time, launch, timezone for display, bin width, thresholds, the ordered list of categories, the code version, and per country the status of the last pull (`ok` or `failed`) and the time its data is from (`as_of`). A server that fails in a pull keeps its counts from the last successful pull.

## Code

`pipeline/` pulls, classifies, bins and publishes; see `pipeline/README.md`. The page (`index.html`, `app.js`) is plain HTML and JavaScript without external libraries. Open it with `?data=<url>/` to read the data files from another location.

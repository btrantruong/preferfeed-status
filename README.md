# preferFeed fielding status

Changelog
- 2026-11-26: panels regrouped (B drop out stats, C request pulse and errors, D data completeness, E user spot check); requests per participant shows one condition at a time.
- 2026-11-25: panel B pages 3 to 5: in session or left, time on the feed, attempt durations (sessions files, detail pull); a local ids report.
- 2026-11-25: panel D: the draw button is replaced by one button per condition that cycles through its participants, plus a dropdown.
- 2026-11-25: panel D: no seed and no inventory-file warning; the button draws another batch of users.
- 2026-11-25: panel D is public: spot_users.json is published with the data when SPOT_PUBLISH is on (participants by database id, the posts they saw, dwell times); a random draw of 12 with a seed.
- 2026-11-25: panel D page 1 redrawn as two stacked panels (batch sums and posts with dwell time as point area; u_long sum and norm).
- 2026-11-25: runs can pull some countries only and countries can launch at different times (pipeline/README.md); the header shows countries not pulled.
- 2026-11-25: renamed panels B and C, reordered the pages of B and D.
- 2026-11-24: added panels A to C (completion status, data completeness and server-side errors, algorithm pipeline), the two-handle window slider, the data file list and the local-only panel D.

Page: https://btrantruong.github.io/preferfeed-status/

The page shows, per country server or for all countries, how many participants started the study since the launch and the status of each at the last data pull. Aggregate counts are published, with one exception: panel E shows, for a list of participants identified by their database id, the posts they were served, the time spent on each post and the algorithm's profile (no survey id, answers or other personal data); `SPOT_PUBLISH=off` in `pipeline/config.env` stops that and removes the published copy.

## Status definitions

One participant is one row of the study's `visited_users` table with `created_at` on or after the launch. Each participant gets exactly one category at the time of the pull, so the shares add up to 100%.

- done: `done` is true (the participant reached the end page through the study timer).
- cancelled: `cancelled` is true and `done` is not. The reason is the last stopping code in the participant's error log, ordered by server time: bot (automated browser detected), idle (too little focus time or too few posts viewed), reload (timeline page reloaded), or other (no stopping code). A participant can restart after bot or idle detection, so the last stop is the one shown.
- incomplete: neither flag is set. possibly in session: created less than `session_min` minutes before the pull, so the status is not final. error logged: at least one logged error code outside `ignore_codes`. no error: the rest.

The thresholds and codes used for a given pull are in `data/meta.json`.

## Panels

The top panel (participants since launch) and its window slider with two draggable handles stay on top. The country control selects the countries for every figure: All pools them by summing their counts, a click keeps one country. Each panel below has a pager; the last page viewed is remembered in the browser.

- A. Completion status: the status of the participants at the last pull (cs0), condition balance (cs1), retaking attempts (cs2).
- B. Drop out stats: in session or left by condition (ss1), time on the feed of done and not-done participants (ss2), duration of each attempt by attempt number and outcome (ss3).
- C. Request pulse & errors: server errors over time (se1), errors by type and sequence (se2), where in the session the error happens (se3), status mix with and without server errors (se4), client-side network failures (se5); algorithm calls and active participants over time (ap1), warm-up exit (ap2).
- D. Data completeness: requests per participant, one condition at a time with a button per condition (dc3), records per done participant (dc2), integrity-flag rate over time (dc1, with an i beside each flag for its definition).
- E. User spot check (sp2, sp1): one participant's batch sums and posts (point area = dwell time) over their u_long sum and norm, and u_long over time. One button per condition selects the next participant of that condition (a click cycles through them) and a dropdown, grouped by condition, selects a specific participant. The panel appears when `data/spot_users.json` exists; a run writes it only when `DETAIL` is basic or full and `INVENTORY_FILE` is set on that machine, and a published copy stays when a later run (for example on a machine without the inventory) does not write one.

Every page has a caption with the quantities on the axes and how they were computed. Participant charts include the participants created inside the window; event charts include the events whose time lies inside it.

## Data files

All files are aggregate counts; only non-zero rows are listed; `bin_start` is UTC ISO 8601 and never finer than the bin (`bin_minutes` for participant files, `event_bin_minutes` for event files). `data/meta.json` lists the files that were published (`files`, with their columns, window kind and, per country, the time the rows are from), the chart parameters (`params`), the detail pull status per country (`detail`), pull time, launch, timezone for display, bin widths, thresholds, the ordered categories, the code version and per country the status of the last pull (`ok` or `failed`) and the time its data is from (`as_of`). A server that fails keeps its rows from the last successful pull; the same holds for the detail files (record_entry and algo_exchange counts) when only their pull fails or is switched off.

| file | one row is | columns | page |
|---|---|---|---|
| `status_bins.csv` | participants in a bin | bin_start, country, status, reason, n | top, cs0 |
| `status_detail.csv` | participants in a bin | bin_start, country, condition, started, has_server_error, status, reason, n | cs1, se4 |
| `attempts.csv` | participants in a bin | bin_start, country, status, attempts, after_stop, n | cs2 |
| `errors_time.csv` | SERVER_ERROR and CLIENT_* events in an event bin | bin_start, country, code, detail, n | se1, se5 |
| `errors_age.csv` | error events by creation bin and age | bin_start, country, code, age_bin, n | se3 |
| `error_flow.csv` | participants going from one error type to the next | bin_start, country, step, from_node, to_node, n | se2 |
| `flags.csv` | done participants in a bin | bin_start, country, n_done, no_records, no_init, no_next_batch, request_gap, condition_mismatch, never_left_warmup, any_fail | dc1 |
| `records_hist.csv` | done participants by record count | bin_start, country, records_bin, n | dc2 |
| `requests_hist.csv` | done participants by requests | bin_start, country, condition, requests, n | dc3 |
| `requests_diff_hist.csv` | done participants by requests minus viewed_posts / batch size | bin_start, country, condition, diff, n | dc3 |
| `algo_calls.csv` | algo_exchange rows in an event bin | bin_start, country, endpoint, n | ap1 |
| `active.csv` | active participants in an event bin | bin_start, country, n_active | ap1 |
| `warmup.csv` | next_batch exchanges of non-RANDOM participants | bin_start, country, condition, request_index, n, n_algorithm | ap2 |

Definitions that go beyond the status page: a retake is a timeline start after the first (visited_users.attempt, or the number of init exchanges where that column does not exist); after_stop marks participants with at least two starts and a stop code logged before the last start. Flags are evaluated on the final attempt of each done participant (the logic of check_user() in daily_check.py; never_left_warmup uses algo_state.phase). Details of error entries are published only if they are an exception class name (SERVER_ERROR) or HTTP followed by three digits (client codes); everything else is published as other.

## Code

`pipeline/` pulls, classifies, bins and publishes; see `pipeline/README.md`. The page (`index.html`, `js/`) is plain HTML and ES modules without external libraries or a build step (`main.js` boots, `select.js` filters, `charts/` holds one module per figure); `node --test js/tests/*.test.js` runs its tests. Open it with `?data=<url>/` to read the data files from another location.

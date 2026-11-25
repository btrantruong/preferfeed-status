improve the visualizations in preferfeed-status. plan first 
make 3 panels 
Keep top panel (no participants since launch & time window slider)
- Make the time window slider into a two-sided, draggable slider 
- A panel with multiple figures are paginated to navigate between them 
A. Completion status 
0. Current viz (Status of these participants at the last pull) goes here 
1. Condition balance.
    * x: condition.
    * y: number of participants who started and number who finished, per country.
    * A lopsided finish rate across conditions means attrition differs by arm. That is a design issue, separate from errors.

B. Data completeness (per participant, aggregated)

1. Integrity-flag rate over time.
    * x: hour created (created_at).
    * y: share of done participants with each flag.
    * Flags: no_records, no_init, no_next_batch, request_gap, condition_mismatch, and never_left_warmup as a warning.
    * The logic already exists in check_user() in daily_check.py, so it can be reused even though that script is otherwise ignored.
    * It shows done participants whose behavioural or algorithm logs are missing.
2. Records per done participant.
    * x: number of record_entry rows, binned.
    * y: count of participants, one panel per country.
    * A spike at 0 or at very low counts means data was lost.
3. Requests per participant.
    * x: request_index max + 1.
    * y: count of participants, split by condition.
    * Compare this with viewed_posts / batch size. A mismatch points to lost or doubled requests.
4. Session coverage.
    * Scatter of focused_seconds against viewed_posts for done participants.
    * Reference lines at 360 s and 20 posts, the idle-check thresholds.
    * Points below the thresholds that are still done would point to an inconsistency in the idle logic.

B. Server-side errors
1. Server errors over time.
    * x: timestamp_server, in 5- or 10-minute bins.
    * y: number of SERVER_ERROR events, one line per country.
    * Bursts that line up across countries point to shared infrastructure, such as the algorithm server. Bursts on one country only point to that server.
2. Server errors by exception type.
    * SERVER_ERROR events broken down by detail, which holds the exception class name (e.g. InternalServerError), per country.
3. Where in the session the error happens.
    * x: time since the participant's created_at when the error was logged.
    * y: count of errors, faceted by code.
    * Separates failures at startup (init) from failures partway through (next_batch).
4. Status mix with and without server errors.
    * Stacked bars of done, cancelled and neither, for participants with at least one SERVER_ERROR versus participants with none.
    * Shows whether server errors are linked to people dropping out.
5. Client-side network failures over time.
    * CLIENT_TRACKING_SEND_FAILED (HTTP 502), CLIENT_FEED_INIT_FAILED and CLIENT_FEED_BATCH_LOAD_FAILED, on the same time axis as chart 6.
    * A 502 seen by the client is a server or proxy failure that may never appear in SERVER_ERROR.
C. Algorithm pipeline
1. Algorithm calls over time.
    * x: time.
    * y: number of algo_exchange rows per endpoint (init, next_batch), per country.
    * Plot this next to the number of active participants. Calls dropping while participants stay active means the algorithm server stalled.
2. Warm-up exit.
    * Share of non-RANDOM participants whose next_batch algo_type switches from RANDOM to their own condition.
    * Shown by condition and by batch index.
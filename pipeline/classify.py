"""Give each participant one status and reason. Pure functions, no DB access.

status      reason
done        done            done is True
cancelled   <stop label>    cancelled is True and done is not; the label of the last stopping code
            other           (by timestamp_server) in the error log, or "other" if there is none
incomplete  in_session      neither flag; created less than session_min minutes before the pull
            error_logged    neither flag; at least one code not in ignore_codes
            no_error        neither flag; no such code
"""
import json

import pandas as pd

STATUSES = ["done", "cancelled", "incomplete"]
INCOMPLETE_REASONS = ["in_session", "error_logged", "no_error"]
ERROR_COLUMNS = ["country", "user_id", "pos", "code", "detail", "timestamp_server"]
OUT_COLUMNS = ["country", "user_id", "created_at", "status", "reason"]


def categories(stop_codes):
    """Ordered (status, reason) pairs, as shown on the page."""
    return ([("done", "done")]
            + [("cancelled", label) for label in stop_codes] + [("cancelled", "other")]
            + [("incomplete", r) for r in INCOMPLETE_REASONS])


def explode_errors(df, country):
    """One row per logged error. Copied from 2026-11-20-daily-status/scripts/02_daily_status.py,
    plus `pos` (position in the participant's log) as a tie-breaker for equal timestamps."""
    rows = []
    for uid, raw in zip(df["id"], df["errors"]):
        if raw is None or (isinstance(raw, float) and pd.isna(raw)):
            continue
        entries = json.loads(raw) if isinstance(raw, str) else raw
        for pos, e in enumerate(entries or []):
            rows.append({"country": country, "user_id": uid, "pos": pos, "code": e.get("code"),
                         "detail": e.get("detail"),
                         "timestamp_server": e.get("timestamp_server")})
    return pd.DataFrame(rows, columns=ERROR_COLUMNS)


def last_stop_label(errors_long, stop_codes):
    """(country, user_id) -> label of the last stopping code. Missing timestamps sort first."""
    code_to_label = {code: label for label, code in stop_codes.items()}
    stops = errors_long[errors_long["code"].isin(list(code_to_label))].copy()
    if stops.empty:
        return {}
    stops["ts"] = pd.to_numeric(stops["timestamp_server"], errors="coerce")
    stops = stops.sort_values(["country", "user_id", "ts", "pos"], na_position="first",
                              kind="stable")
    last = stops.groupby(["country", "user_id"], sort=False).tail(1)
    return {(c, u): code_to_label[code] for c, u, code in zip(last["country"], last["user_id"],
                                                             last["code"])}


def users_with_error(errors_long, ignore_codes):
    counted = errors_long[~errors_long["code"].isin(list(ignore_codes))]
    return set(zip(counted["country"], counted["user_id"]))


def classify(visited, errors_long, pulled_at_ms, session_min, ignore_codes, stop_codes):
    """visited: country, id, created_at (epoch ms), done, cancelled.
    errors_long: output of explode_errors (all countries).
    Returns one row per participant with OUT_COLUMNS."""
    if visited.empty:
        return pd.DataFrame(columns=OUT_COLUMNS)
    done = visited["done"].eq(True).to_numpy()
    cancelled = visited["cancelled"].eq(True).to_numpy()
    keys = list(zip(visited["country"], visited["id"]))
    stop_label = last_stop_label(errors_long, stop_codes)
    with_error = users_with_error(errors_long, ignore_codes)
    session_ms = session_min * 60_000
    created = visited["created_at"].astype("int64").to_numpy()

    status, reason = [], []
    for i, key in enumerate(keys):
        if done[i]:
            status.append("done"); reason.append("done")
        elif cancelled[i]:
            status.append("cancelled"); reason.append(stop_label.get(key, "other"))
        else:
            status.append("incomplete")
            if pulled_at_ms - created[i] < session_ms:
                reason.append("in_session")
            elif key in with_error:
                reason.append("error_logged")
            else:
                reason.append("no_error")
    return pd.DataFrame({"country": visited["country"].to_numpy(),
                         "user_id": visited["id"].to_numpy(),
                         "created_at": created, "status": status, "reason": reason},
                        columns=OUT_COLUMNS)

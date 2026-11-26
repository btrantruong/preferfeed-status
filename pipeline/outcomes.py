"""Outcome and retries of each participant, for panel A. Pure functions, no DB access.

error       a logged code outside OUTCOME_IGNORE_CODES (the restart marker never counts). Software stops and
            technical failures both count. A cancelled participant without such a code has an error of type other.
retried     at least one TIMELINE_RESTARTED entry, or blocked as automated when the row was created and started
            since (the app logs no restart marker in that case)
attempt     the time between two restarts; the first one begins with the session
outcome     one per participant
  done_first, done_retry      done, without or with a retry
  in_session                  not done, not cancelled and inside the session time (rule of panel B)
  left_no_error               left: no error, no retry
  left_no_error_retried       left: no error, retried
  left_retried_after_error    left: an error was logged before the last restart
  left_error_no_retry         left: errors, none of them before a restart
last_error  type of the last error of a participant who left with errors, else none
retries     number of retries
trigger     type of the last error of the attempt that the last restart ended; none if nothing was logged
            (also for participants without a retry)
retry_outcome  for retried participants: done, in_session, left_final_error (an error in the last attempt) or
            left_no_final_error; empty otherwise
"""
import numpy as np
import pandas as pd

RESTART_CODE = "TIMELINE_RESTARTED"
BOT_LABEL = "bot"          # label of the automated-browser code in STOP_CODES
NONE, OTHER = "none", "other"
LEFT_WITH_ERROR = ["left_error_no_retry", "left_retried_after_error"]
COLUMNS = ["outcome", "last_error", "retries", "trigger", "retry_outcome"]
MIN = 60_000


def type_of_codes(stop_codes, server_code, client_codes):
    """{code: type}: the stop labels, server and client; every other code is of type other."""
    out = {code: label for label, code in stop_codes.items()}
    out[server_code] = "server"
    out.update({code: "client" for code in client_codes})
    return out


def restart_times(log, created_ms, started, bot_code, bot_create_ms):
    """Sorted restart times of one participant. log: [(ts, pos, code)] in time order.

    A participant blocked as automated when the row was created, who has started since, has one more restart,
    placed just after that entry."""
    times = [ts for ts, _, code in log if code == RESTART_CODE]
    if started and bot_code:
        blocked = [ts for ts, _, code in log if code == bot_code and abs(ts - created_ms) <= bot_create_ms]
        if blocked:
            times.append(min(blocked) + 1)
    return sorted(times)


def classify_one(done, cancelled, in_session, errors, restarts):
    """errors: [(ts, type)] of the counted errors in time order. restarts: sorted times. Returns COLUMNS."""
    retried = bool(restarts)
    last = restarts[-1] if retried else -np.inf
    previous = restarts[-2] if len(restarts) > 1 else -np.inf
    ended = [t for ts, t in errors if previous <= ts < last] if retried else []
    # a cancelled participant without a logged code was stopped in the last attempt
    unlogged_stop = cancelled and not errors
    before = retried and any(ts < last for ts, _ in errors)
    final_error = unlogged_stop or any(ts >= last for ts, _ in errors)
    last_error = NONE
    if done:
        outcome, retry_outcome = ("done_retry" if retried else "done_first"), "done"
    elif in_session and not cancelled:
        outcome, retry_outcome = "in_session", "in_session"
    else:
        retry_outcome = "left_final_error" if final_error else "left_no_final_error"
        if not (errors or unlogged_stop):
            outcome = "left_no_error_retried" if retried else "left_no_error"
        else:
            outcome = "left_retried_after_error" if before else "left_error_no_retry"
            last_error = errors[-1][1] if errors else OTHER
    return {"outcome": outcome, "last_error": last_error, "retries": len(restarts),
            "trigger": ended[-1] if ended else NONE, "retry_outcome": retry_outcome if retried else ""}


def logs_by_participant(errors_long):
    """{(country, user_id): [(ts, pos, code)]} ordered by server time, then position. A missing time sorts first."""
    if errors_long.empty:
        return {}
    d = errors_long.assign(ts=pd.to_numeric(errors_long["ts"], errors="coerce").fillna(-np.inf))
    d = d.sort_values(["country", "user_id", "ts", "pos"], kind="stable")
    return {key: list(zip(g["ts"], g["pos"], g["code"])) for key, g in d.groupby(["country", "user_id"], sort=False)}


def add_outcomes(P, errors_long, sessions, now_ms, stop_codes, p):
    """P (country, user_id, created_at, status, started) with COLUMNS added.

    sessions: sessions.participants_table of the countries with a detail pull, or None. Its state decides in
    session or left (the rule of panel B). A participant it does not cover is in session while the time since
    the last start (creation or last restart) is below SESSION_REF_FALLBACK_MIN. p = Config.params."""
    if P.empty:
        return P.assign(**{c: pd.Series(dtype="int64" if c == "retries" else "object") for c in COLUMNS})
    types = type_of_codes(stop_codes, p["server_error_code"], p["client_error_codes"])
    ignore = set(p["outcome_ignore_codes"]) | {RESTART_CODE}
    logs = logs_by_participant(errors_long)
    state = ({} if sessions is None or sessions.empty or "state" not in sessions else
             dict(zip(zip(sessions["country"], sessions["user_id"]), sessions["state"])))
    rows = []
    for r in P[["country", "user_id", "created_at", "status", "started"]].itertuples(index=False):
        key = (r.country, r.user_id)
        log = logs.get(key, [])
        started = r.started is True or r.started == 1
        restarts = restart_times(log, r.created_at, started, stop_codes.get(BOT_LABEL),
                                 p["outcome_bot_create_s"] * 1000)
        errors = [(ts, types.get(code, OTHER)) for ts, _, code in log if code not in ignore]
        if key in state:
            in_session = state[key] == "in_session"
        else:
            last_start = max([r.created_at] + restarts)
            in_session = now_ms - last_start < p["session_ref_fallback_min"] * MIN
        rows.append(classify_one(r.status == "done", r.status == "cancelled", in_session, errors, restarts))
    return P.assign(**{c: [row[c] for row in rows] for c in COLUMNS})

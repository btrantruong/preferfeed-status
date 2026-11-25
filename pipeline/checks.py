"""Attempts and integrity flags of done participants. Pure functions, no DB access.

Attempts. A start of the timeline after the first is a retake. Every start has one init exchange in
algo_exchange. The number of starts is visited_users.attempt when that column exists and is not null,
otherwise the number of init rows. The final attempt is the one with the highest number: the exchange rows
whose attempt equals visited_users.attempt, or, without an attempt number, the rows from the last init on.

Flags. check_user() of fielding/2026-11-20-daily-check/daily_check.py, evaluated on the final attempt (a
restart reuses request_index from 0, so all rows of a retaker would show a request gap), with one change:
never_left_warmup uses algo_state.phase when the participant has phase values.
"""
import numpy as np
import pandas as pd

FAIL_FLAGS = ["no_records", "no_init", "no_next_batch", "request_gap", "condition_mismatch"]
WARN_FLAGS = ["never_left_warmup"]
ALL_FLAGS = FAIL_FLAGS + WARN_FLAGS
EX_COLUMNS = ["country", "user_id", "endpoint", "algo_type", "timestamp_server", "request_index", "phase"]


def segment_attempts(ex, visited_attempt=None):
    """Add attempt_id (this row's attempt) and final_attempt (the participant's highest) to ex.

    ex: EX_COLUMNS plus optionally attempt. visited_attempt: {(country, user_id): attempt} from
    visited_users.attempt, or None. Rows of a participant use the logged attempt numbers only if both the
    participant's visited_users.attempt and the rows' attempt are known; otherwise init rows are counted."""
    ex = ex.sort_values(["country", "user_id", "timestamp_server"], kind="stable").copy()
    key = list(zip(ex["country"], ex["user_id"]))
    ex["attempt_id"] = (ex["endpoint"] == "init").astype(int).groupby([ex["country"], ex["user_id"]]).cumsum()
    ex["final_attempt"] = ex.groupby(["country", "user_id"])["attempt_id"].transform("max")
    if visited_attempt and "attempt" in ex.columns:
        vis = pd.Series([visited_attempt.get(k) for k in key], index=ex.index, dtype="float64")
        known = vis.notna() & pd.to_numeric(ex["attempt"], errors="coerce").notna()
        # a participant is read by number only if every one of their rows carries a number
        all_known = known.groupby([ex["country"], ex["user_id"]]).transform("all")
        ex.loc[all_known, "attempt_id"] = pd.to_numeric(ex.loc[all_known, "attempt"]).astype(int)
        ex.loc[all_known, "final_attempt"] = vis[all_known].astype(int)
    return ex


def starts_per_participant(participants, ex, visited_attempt=None):
    """Series indexed like participants: number of timeline starts (0 = no recorded start), NaN when neither
    the attempt column nor the exchanges are available."""
    keys = list(zip(participants["country"], participants["user_id"]))
    out = []
    n_init = ({} if ex is None else
              ex[ex["endpoint"] == "init"].groupby(["country", "user_id"]).size().to_dict())
    for k in keys:
        att = (visited_attempt or {}).get(k)
        if att is not None and not pd.isna(att):
            out.append(float(att))
        elif ex is not None:
            out.append(float(n_init.get(k, 0)))
        else:
            out.append(np.nan)
    return pd.Series(out, index=participants.index)


def final_start_ms(ex):
    """{(country, user_id): time of the init exchange that opened the final attempt}."""
    if ex is None or ex.empty:
        return {}
    fin = ex[(ex["endpoint"] == "init") & (ex["attempt_id"] == ex["final_attempt"])]
    g = fin.groupby(["country", "user_id"])["timestamp_server"].min()
    return g.to_dict()


def retook_after_stop(participants, starts, events, stop_codes, final_start):
    """Boolean Series: at least two starts and a stop code logged before the final start.

    events: errors_long (country, user_id, code, timestamp_server). final_start: {(country, user_id): ms}
    (from final_start_ms). Without a final start time, the time of the last TIMELINE_RESTARTED entry is used;
    without either, any stop code counts."""
    stops = set(stop_codes)
    ev = events.copy()
    ev["ts"] = pd.to_numeric(ev["timestamp_server"], errors="coerce")
    stop_ts = ev[ev["code"].isin(stops)].groupby(["country", "user_id"])["ts"].apply(list).to_dict()
    restart_ts = ev[ev["code"] == "TIMELINE_RESTARTED"].groupby(["country", "user_id"])["ts"].max().to_dict()
    out = []
    for key, n in zip(zip(participants["country"], participants["user_id"]), starts):
        if not (n >= 2) or key not in stop_ts:
            out.append(False)
            continue
        t = final_start.get(key, restart_ts.get(key))
        out.append(True if t is None or pd.isna(t) else any(pd.isna(x) or x < t for x in stop_ts[key]))
    return pd.Series(out, index=participants.index)


def record_thresholds(participants, final_start, margin_ms):
    """Lower time bound of the record_entry rows of each participant's final attempt: ATTEMPT_MARGIN_S before
    the final init for a retaker, the session creation otherwise (no row can precede it).
    Returns a DataFrame country, user_id, since_ms."""
    since = []
    for key, created, n in zip(zip(participants["country"], participants["user_id"]),
                               participants["created_at"], participants["starts"]):
        t = final_start.get(key)
        since.append(int(t) - margin_ms if (n >= 2 and t is not None) else int(created))
    return pd.DataFrame({"country": participants["country"].to_numpy(),
                         "user_id": participants["user_id"].to_numpy(), "since_ms": since})


def integrity_flags(condition, n_records, ex_final):
    """Flags of one done participant on the exchanges of the final attempt (EX_COLUMNS rows)."""
    nb = ex_final[ex_final["endpoint"] == "next_batch"]
    idx = sorted(int(i) for i in ex_final["request_index"].dropna())
    out = {"no_records": bool(n_records == 0),
           "no_init": not (ex_final["endpoint"] == "init").any(),
           "no_next_batch": bool(nb.empty),
           "request_gap": bool(idx) and idx != list(range(max(idx) + 1)),
           "condition_mismatch": bool((~nb["algo_type"].isin(["RANDOM", condition])).any())}
    if nb["phase"].notna().any():
        left = (nb["phase"] == "algorithm").any()
    else:
        left = (nb["algo_type"] == condition).any()
    out["never_left_warmup"] = bool(condition != "RANDOM" and len(nb) > 0 and not left)
    out["requests"] = (max(idx) + 1) if idx else None
    out["n_next_batch"] = int(len(nb))
    return out


def flags_table(done, ex_final_by_key, counts):
    """One row per done participant: the flags, requests (request_index max + 1) and n_records.

    done: participants with country, user_id, condition. ex_final_by_key: {(country, user_id): final rows}.
    counts: {(country, user_id): n_records of the final attempt}."""
    empty = pd.DataFrame(columns=EX_COLUMNS)
    rows = []
    for c, u, cond in zip(done["country"], done["user_id"], done["condition"]):
        g = ex_final_by_key.get((c, u), empty)
        n = counts.get((c, u), 0)
        f = integrity_flags(cond, n, g)
        rows.append({"country": c, "user_id": u, "n_records": int(n), **f})
    return pd.DataFrame(rows)

"""Attempts, time on the feed and in-session / left state per participant. Pure functions, no DB access.

Attempt table (attempts_table): one row per participant and attempt.
  start       the init exchange of the attempt (the first record of the attempt if there is no init)
  end         the last record_entry row of the attempt (the last exchange if the attempt has no records)
  duration    end minus start in minutes, at least 0 (records begin a few seconds before the init)
  gap_before  start minus the end of the previous attempt
  codes       error codes logged during the attempt (TIMELINE_RESTARTED left out), by timestamp
  ends_as     restarted for every attempt but the last; done, cancelled or incomplete for the last one

Participant table (participants_table): entry (created_at, or the final init exchange when there are two or more
inits, that is after a restart), time on the feed (total over attempts, and the final attempt), and the state at
the pull time:
  done, stopped (cancelled)           from the status
  in_session / left, time rule        not done, not cancelled: time since entry below T_ref gives in_session
  silence rule (check)                the last record is at most silence_s old gives in_session, older gives left
T_ref is the ref_quantile value of (last record minus entry) of done participants with records once there are at
least ref_min_n of them, else the fixed fallback (the 10 minutes of the timeline design).
"""
import numpy as np
import pandas as pd

MIN = 60_000
ATTEMPT_COLUMNS = ["country", "user_id", "attempt", "start_ms", "end_ms", "duration_min", "gap_before_min",
                   "n_records", "n_next_batch", "codes", "ends_as"]


def status_of(done, cancelled):
    return "done" if done else "cancelled" if cancelled else "incomplete"


def attempts_table(P, ex, rec, events):
    """P: country, user_id, status. ex: country, user_id, endpoint, timestamp_server, attempt_id (or None).
    rec: country, user_id, attempt, n_records, first_record_ms, last_record_ms (or None).
    events: errors_long with country, user_id, code, ts (ms). Returns ATTEMPT_COLUMNS."""
    ex = ex if ex is not None and not ex.empty else pd.DataFrame(columns=["country", "user_id", "endpoint", "timestamp_server", "attempt_id"])
    rec = rec if rec is not None and not rec.empty else pd.DataFrame(columns=["country", "user_id", "attempt", "n_records", "first_record_ms", "last_record_ms"])
    inits = ex[ex["endpoint"] == "init"].groupby(["country", "user_id", "attempt_id"])["timestamp_server"].min()
    last_ex = ex.groupby(["country", "user_id", "attempt_id"])["timestamp_server"].max()
    n_nb = ex[ex["endpoint"] == "next_batch"].groupby(["country", "user_id", "attempt_id"]).size()
    r = rec.set_index(["country", "user_id", "attempt"])
    keys = set(inits.index) | set(last_ex.index) | set(r.index)
    rows = []
    for k in sorted(keys):
        first_rec = r["first_record_ms"].get(k, np.nan)
        start = inits.get(k, first_rec)
        end = r["last_record_ms"].get(k, last_ex.get(k, np.nan))
        rows.append({"country": k[0], "user_id": k[1], "attempt": int(k[2]), "start_ms": start, "end_ms": end,
                     "n_records": int(r["n_records"].get(k, 0)), "n_next_batch": int(n_nb.get(k, 0))})
    a = pd.DataFrame(rows, columns=["country", "user_id", "attempt", "start_ms", "end_ms", "n_records", "n_next_batch"])
    if a.empty:
        return pd.DataFrame(columns=ATTEMPT_COLUMNS)
    a = _fill_missing_attempts(a, P)
    a = a.sort_values(["country", "user_id", "attempt"]).reset_index(drop=True)
    a["duration_min"] = ((a["end_ms"] - a["start_ms"]) / MIN).clip(lower=0)
    grp = a.groupby(["country", "user_id"])
    prev_end = grp["end_ms"].transform(lambda x: x.ffill().shift(1))         # the end of the last attempt that left data
    a["gap_before_min"] = ((a["start_ms"] - prev_end) / MIN).clip(lower=0)
    a["codes"] = _codes_per_attempt(a, events)
    last = grp["attempt"].transform("max") == a["attempt"]
    st = P.set_index(["country", "user_id"])["status"]
    final = pd.Series([st.get((c, u), "incomplete") for c, u in zip(a["country"], a["user_id"])], index=a.index)
    a["ends_as"] = np.where(last, final, "restarted")
    return a[ATTEMPT_COLUMNS]


def _fill_missing_attempts(a, P):
    """An attempt number can leave no init and no record (the timeline page never loaded). Rows for the numbers
    between 1 and the participant's highest attempt (visited_users.attempt where known) are added, without times."""
    top = a.groupby(["country", "user_id"])["attempt"].max()
    if "attempt" in P:
        vis = pd.to_numeric(P.set_index(["country", "user_id"])["attempt"], errors="coerce").dropna()
        top = top.combine(vis, max, fill_value=0)
    have = set(zip(a["country"], a["user_id"], a["attempt"]))
    extra = [{"country": c, "user_id": u, "attempt": k, "start_ms": np.nan, "end_ms": np.nan, "n_records": 0, "n_next_batch": 0}
             for (c, u), n in top.items() for k in range(1, int(n) + 1) if (c, u, k) not in have and (c, u) in set(zip(a["country"], a["user_id"]))]
    return pd.concat([a, pd.DataFrame(extra, columns=a.columns)], ignore_index=True) if extra else a


def _codes_per_attempt(a, events):
    """Comma separated error codes of each attempt, by time: from this attempt's start to the next one's start."""
    out = [""] * len(a)
    if events is None or events.empty:
        return out
    ev = events[events["code"] != "TIMELINE_RESTARTED"]
    by = {k: g for k, g in ev.groupby(["country", "user_id"])}
    nxt = a.groupby(["country", "user_id"])["start_ms"].shift(-1)
    for i, r in enumerate(a.itertuples()):
        g = by.get((r.country, r.user_id))
        if g is None or pd.isna(r.start_ms):
            continue
        hi = nxt.iloc[i] if pd.notna(nxt.iloc[i]) else np.inf
        sel = g[(g["ts"] >= r.start_ms) & (g["ts"] < hi)]
        out[i] = ",".join(sorted(set(sel["code"])))
    return out


def reference(parts, quantile, min_n, fallback_min):
    """T_ref and the median of (last record - entry) of done participants with records. Returns a dict."""
    d = parts[(parts["status"] == "done") & parts["last_record_ms"].notna()]
    x = ((d["last_record_ms"] - d["entry_ms"]) / MIN).dropna()
    if len(x) >= min_n:
        return {"source": "launch", "n": int(len(x)), "t_ref_min": float(x.quantile(quantile)), "median_min": float(x.median())}
    return {"source": "fallback", "n": int(len(x)), "t_ref_min": float(fallback_min), "median_min": None}


def participants_table(P, att, now_ms, p):
    """One row per participant (rows of P): entry, time on the feed, rules and state. p = Config.params."""
    if P.empty:
        return P.assign(entry_ms=np.nan, n_attempts=0, total_min=np.nan, final_min=np.nan, last_record_ms=np.nan,
                        min_since_entry=np.nan, min_since_last_record=np.nan, time_rule=None, silence_rule=None,
                        state=None, disagree=False)
    a = att.groupby(["country", "user_id"]).agg(n_attempts=("attempt", "max"), total_min=("duration_min", "sum"))
    last_rec = att[att["n_records"] > 0].groupby(["country", "user_id"])["end_ms"].max()
    final = att.sort_values("attempt").groupby(["country", "user_id"]).tail(1).set_index(["country", "user_id"])
    inits = att.groupby(["country", "user_id"])["attempt"].size()
    final_start = final["start_ms"]
    d = P.copy()
    key = list(zip(d["country"], d["user_id"]))
    d["n_attempts"] = [int(a["n_attempts"].get(k, 0)) for k in key]
    d["total_min"] = [a["total_min"].get(k, np.nan) for k in key]
    d["final_min"] = [final["duration_min"].get(k, np.nan) for k in key]
    d["last_record_ms"] = [last_rec.get(k, np.nan) for k in key]
    multi = np.array([inits.get(k, 0) >= 2 for k in key])
    d["entry_ms"] = np.where(multi, [final_start.get(k, np.nan) for k in key], d["created_at"].astype("float64"))
    ref = reference(d, p["session_ref_quantile"], p["session_ref_min_n"], p["session_ref_fallback_min"])
    d["min_since_entry"] = (now_ms - d["entry_ms"]) / MIN
    d["min_since_last_record"] = (now_ms - d["last_record_ms"]) / MIN
    time_rule = np.where(d["min_since_entry"] < ref["t_ref_min"], "in_session", "left")
    silence = np.where(d["last_record_ms"].isna(), None,
                       np.where(d["min_since_last_record"] * 60 <= p["session_silence_s"], "in_session", "left"))
    d["time_rule"], d["silence_rule"] = time_rule, silence
    use_silence = p["session_rule"] == "silence"
    live = np.where(use_silence & pd.notna(d["silence_rule"]), d["silence_rule"], d["time_rule"])
    d["state"] = np.where(d["status"] == "done", "done", np.where(d["status"] == "cancelled", "stopped", live))
    d["disagree"] = (d["status"] == "incomplete") & pd.notna(d["silence_rule"]) & (d["silence_rule"] != d["time_rule"])
    d.attrs["reference"] = ref
    return d

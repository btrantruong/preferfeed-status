"""Detail pull: algo_exchange rows, record_entry counts of done participants, active participants, spot rows.

A separate failure domain: a country whose detail pull fails or times out keeps its last published detail
rows (aggregate.carry_over), and the core files are still published. DETAIL=off skips the whole pull,
basic runs Q1 (record counts), Q2 (exchanges) and Q4 (spot rows), full adds Q3 (active participants).

record_entry is the large table (millions of rows, only a primary key). Two things bound its cost:
  counts of done participants are cached in OUTDIR (detail_cache.json) and are final once the participant's
  session cannot write any more (counted at least SESSION_MIN minutes after the final start); only the other
  participants are counted again, from the record_id of their earliest start (bisection, see db.py);
  active participants per bin are cached the same way: a bin is final when it ended at least SESSION_MIN minutes
  before it was counted, so only the last bins are queried.
"""
import json
import os

import numpy as np
import pandas as pd

import checks

CACHE_FILE = "detail_cache.json"


def load_cache(outdir):
    try:
        with open(os.path.join(outdir, CACHE_FILE)) as fh:
            c = json.load(fh)
    except (OSError, ValueError):
        c = {}
    c.setdefault("records", {})
    c.setdefault("active", {})
    return c


def save_cache(outdir, cache):
    path = os.path.join(outdir, CACHE_FILE)
    with open(path + ".tmp", "w") as fh:
        json.dump(cache, fh)
    os.replace(path + ".tmp", path)


def count_records(source, cc, thresholds, cache, pulled_ms, session_min):
    """Record rows of the final attempt for each row of thresholds (user_id, since_ms, created_at, final_start).
    Returns {user_id: n}; counts that are final come from the cache."""
    cc_cache = cache["records"].setdefault(cc, {})
    session_ms = session_min * 60_000
    out, todo = {}, []
    for r in thresholds.itertuples():
        e = cc_cache.get(str(r.user_id))
        if e and e["since"] == int(r.since_ms) and e["final"]:
            out[int(r.user_id)] = e["n"]
        else:
            todo.append(r)
    if todo:
        fresh = source.record_counts(cc, pd.DataFrame({"user_id": [t.user_id for t in todo],
                                                       "since_ms": [t.since_ms for t in todo]}))
        for t in todo:
            n = int(fresh[int(t.user_id)])
            out[int(t.user_id)] = n
            start = max(int(t.created_at), int(t.final_start) if t.final_start == t.final_start else 0)
            cc_cache[str(t.user_id)] = {"n": n, "since": int(t.since_ms),
                                        "final": bool(pulled_ms >= start + session_ms)}
    return out


def active_bins(source, cc, launch_ms, bin_ms, cache, pulled_ms, session_min, first_ms=None):
    """DataFrame bin_ms, n_active for all bins since the country's launch (first_ms; default launch_ms); bins are
    on the grid of launch_ms; bins that ended long enough ago come from the cache."""
    first = launch_ms if first_ms is None else launch_ms + ((first_ms - launch_ms) // bin_ms) * bin_ms
    c = cache["active"].setdefault(cc, {"final_until": first, "bins": {}})
    safe = pulled_ms - session_min * 60_000
    start = int(c["final_until"])
    fresh = source.active(cc, launch_ms, start, bin_ms)
    for b, n in zip(fresh["bin_ms"], fresh["n_active"]):
        c["bins"][str(int(b))] = int(n)
    # bins that ended before `safe` are final
    c["final_until"] = max(start, launch_ms + ((safe - launch_ms) // bin_ms) * bin_ms) if safe > launch_ms else start
    return pd.DataFrame({"bin_ms": [int(b) for b in c["bins"]], "n_active": list(c["bins"].values())})


def run_country(source, cfg, cc, P_cc, launch_ms, end_ms, pulled_ms, cache, mode, cc_launch_ms=None):
    """Detail rows of one country. Returns dict ex (with attempt ids), starts, final_start, counts, active.
    Raises on a failed query (the caller marks the country failed)."""
    p = cfg.params
    cc_launch_ms = launch_ms if cc_launch_ms is None else cc_launch_ms
    ex = source.exchanges(cc, cc_launch_ms, end_ms)
    visited_attempt = {(cc, u): a for u, a in zip(P_cc["user_id"], P_cc["attempt"]) if a is not None and not pd.isna(a)}
    seg = checks.segment_attempts(ex, visited_attempt) if not ex.empty else ex.assign(
        attempt_id=pd.Series(dtype="int64"), final_attempt=pd.Series(dtype="int64"))
    starts = checks.starts_per_participant(P_cc, seg, visited_attempt)
    final_start = checks.final_start_ms(seg)
    done = P_cc[P_cc["status"] == "done"].assign(starts=starts.reindex(P_cc[P_cc["status"] == "done"].index))
    thr = checks.record_thresholds(done, final_start, p["attempt_margin_s"] * 1000)
    thr["created_at"] = done["created_at"].to_numpy()
    thr["final_start"] = [final_start.get((cc, u), np.nan) for u in done["user_id"]]
    counts = count_records(source, cc, thr, cache, pulled_ms, cfg.session_min)
    active = None
    if mode == "full":
        active = active_bins(source, cc, launch_ms, p["event_bin_minutes"] * 60_000, cache, pulled_ms, cfg.session_min,
                             first_ms=cc_launch_ms)
        active["country"] = cc
    return {"ex": seg, "starts": starts, "final_start": final_start,
            "counts": {(cc, u): n for u, n in counts.items()}, "active": active}


def empty_result():
    ex = pd.DataFrame({c: pd.Series(dtype="object") for c in checks.EX_COLUMNS})
    ex["attempt_id"] = pd.Series(dtype="int64"); ex["final_attempt"] = pd.Series(dtype="int64")
    return {"ex": ex, "starts": pd.Series(dtype="float64"), "final_start": {}, "counts": {}, "active": None}


def run(cfg, source, P, launch_ms, end_ms, pulled_ms, ok_countries, cache, launch_cc=None):
    """All countries. Returns (results {cc: dict}, status {cc: ok|failed|off|not_pulled}, errors {cc: message}).
    launch_cc: {cc: launch in ms} for countries that launch later than launch_ms."""
    launch_cc = launch_cc or {}
    mode = cfg.params["detail"]
    results, status, errors = {}, {}, {}
    for cc in cfg.countries:
        if cc not in cfg.pulled_countries():
            status[cc] = "not_pulled"
            continue
        if mode == "off" or cc not in ok_countries:
            status[cc] = "off" if mode == "off" else "failed"
            continue
        if P[P["country"] == cc].empty:   # nobody yet: nothing to read, and no query is sent
            results[cc] = empty_result()
            status[cc] = "ok"
            continue
        try:
            results[cc] = run_country(source, cfg, cc, P[P["country"] == cc], launch_ms, end_ms, pulled_ms, cache, mode,
                                       launch_cc.get(cc))
            status[cc] = "ok"
        except Exception as e:  # a detail failure must not stop the core files; class name only, no host
            status[cc] = "failed"
            errors[cc] = f"{type(e).__name__}: {str(e).splitlines()[0][:120] if type(e).__name__ != 'OperationalError' else 'connection'}"
    return results, status, errors

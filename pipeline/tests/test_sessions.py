"""sessions.py, the incremental record aggregates (detail.record_attempts), the session files and report.py. No DB, no study data."""
import os
import sys

import numpy as np
import pandas as pd
import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import config as cfgmod  # noqa: E402
import cubes  # noqa: E402
import detail  # noqa: E402
import report  # noqa: E402
import sessions as SS  # noqa: E402

MIN = 60_000
T0 = 1_800_000_000_000
P_DEFAULT = cfgmod.default_params()


def params(**kw):
    return {**P_DEFAULT, **kw}


def pframe(rows):
    """rows: (user_id, status, created_min, condition)."""
    return pd.DataFrame([{"country": "UK", "user_id": u, "status": s, "created_at": T0 + c * MIN, "created_bin": T0, "condition": cond}
                         for u, s, c, cond in rows])


def ex_rows(items):
    """items: (user_id, attempt, endpoint, minute)."""
    return pd.DataFrame([{"country": "UK", "user_id": u, "endpoint": e, "timestamp_server": T0 + m * MIN, "attempt_id": a}
                         for u, a, e, m in items])


def rec_rows(items):
    """items: (user_id, attempt, n, first_minute, last_minute)."""
    return pd.DataFrame([{"country": "UK", "user_id": u, "attempt": a, "n_records": n, "first_record_ms": T0 + f * MIN, "last_record_ms": T0 + l * MIN}
                         for u, a, n, f, l in items])


def events(items):
    return pd.DataFrame([{"country": "UK", "user_id": u, "code": c, "ts": T0 + m * MIN} for u, c, m in items],
                        columns=["country", "user_id", "code", "ts"])


def scenario():
    P = pframe([(1, "done", 0, "RANDOM"), (2, "incomplete", 0, "ATTENTION"), (3, "incomplete", 50, "RANDOM"), (4, "cancelled", 0, "RANDOM")])
    ex = ex_rows([(1, 1, "init", 0), (1, 1, "next_batch", 1),
                  (2, 1, "init", 0), (2, 2, "init", 12), (2, 2, "next_batch", 13),      # user 2 restarts after 12 minutes
                  (3, 1, "init", 50), (4, 1, "init", 0)])
    rec = rec_rows([(1, 1, 20000, -0.1, 9), (2, 1, 300, -0.1, 0.1), (2, 2, 1000, 11.9, 13.5), (3, 1, 400, 49.9, 50.1), (4, 1, 50, -0.1, 0.05)])
    ev = events([(2, "PAGE_RELOAD_DETECTED", 0.05), (2, "TIMELINE_RESTARTED", 12), (4, "IDLE_DETECTED", 0.05)])
    return P, ex, rec, ev


def test_attempt_table_durations_gaps_codes_and_outcome():
    P, ex, rec, ev = scenario()
    a = SS.attempts_table(P, ex, rec, ev).set_index(["user_id", "attempt"])
    assert a.loc[(1, 1), "duration_min"] == pytest.approx(9.0) and a.loc[(1, 1), "ends_as"] == "done"
    assert a.loc[(2, 1), "duration_min"] == pytest.approx(0.1) and a.loc[(2, 1), "ends_as"] == "restarted"
    assert a.loc[(2, 1), "codes"] == "PAGE_RELOAD_DETECTED"                    # the error belongs to attempt 1 by time
    assert a.loc[(2, 2), "codes"] == "" and a.loc[(2, 2), "ends_as"] == "incomplete"   # TIMELINE_RESTARTED is not a reason
    assert a.loc[(2, 2), "gap_before_min"] == pytest.approx(11.9) and np.isnan(a.loc[(2, 1), "gap_before_min"])
    assert a.loc[(4, 1), "ends_as"] == "cancelled" and a.loc[(4, 1), "codes"] == "IDLE_DETECTED"
    assert (a["duration_min"] >= 0).all()                                      # records that start before the init do not give negative times


def test_an_attempt_without_data_gets_a_row_and_the_gap_skips_it():
    P, ex, rec, ev = scenario()
    P = P.assign(attempt=[1, 3, 1, 1])                                          # visited_users says user 2 started three times
    a = SS.attempts_table(P, ex, rec, ev).set_index(["user_id", "attempt"])
    assert (2, 3) in a.index and np.isnan(a.loc[(2, 3), "duration_min"]) and a.loc[(2, 3), "ends_as"] == "incomplete"
    assert a.loc[(2, 2), "ends_as"] == "restarted"                              # attempt 3 is now the last one
    s = SS.participants_table(P, SS.attempts_table(P, ex, rec, ev), T0 + 70 * MIN, params()).set_index("user_id")
    assert s.loc[2, "n_attempts"] == 3
    P2 = P.assign(attempt=[1, 2, 1, 1])
    ex2 = ex_rows([(2, 1, "init", 0), (2, 3, "init", 20)])                      # attempt 2 left nothing, attempt 3 starts later
    rec2 = rec_rows([(2, 1, 100, 0, 1), (2, 3, 100, 20, 21)])
    a2 = SS.attempts_table(P2.assign(attempt=[1, 3, 1, 1]), ex2, rec2, events([])).set_index(["user_id", "attempt"])
    assert a2.loc[(2, 3), "gap_before_min"] == pytest.approx(19.0)             # measured from the end of attempt 1


def test_participant_states_and_rules():
    P, ex, rec, ev = scenario()
    a = SS.attempts_table(P, ex, rec, ev)
    now = T0 + 70 * MIN
    s = SS.participants_table(P, a, now, params(session_ref_min_n=1)).set_index("user_id")
    assert s["state"].to_dict() == {1: "done", 2: "left", 3: "left", 4: "stopped"}
    assert s.loc[2, "entry_ms"] == T0 + 12 * MIN                                # a restart: entry is the final init
    assert s.loc[2, "total_min"] == pytest.approx(0.1 + 1.5) and s.loc[2, "final_min"] == pytest.approx(1.5) and s.loc[2, "n_attempts"] == 2
    ref = s.attrs["reference"]
    assert ref["source"] == "launch" and ref["n"] == 1 and ref["t_ref_min"] == pytest.approx(9.0)
    now = T0 + 53 * MIN                                                         # 3 minutes after user 3 entered
    s = SS.participants_table(P, a, now, params(session_ref_min_n=1)).set_index("user_id")
    assert s.loc[3, "state"] == "in_session" and s.loc[3, "time_rule"] == "in_session" and s.loc[3, "silence_rule"] == "left" and bool(s.loc[3, "disagree"])
    silent = SS.participants_table(P, a, now, params(session_ref_min_n=1, session_rule="silence")).set_index("user_id")
    assert silent.loc[3, "state"] == "left"
    fallback = SS.participants_table(P, a, now, params()).attrs["reference"]  # one done participant is below SESSION_REF_MIN_N
    assert fallback["source"] == "fallback" and fallback["t_ref_min"] == 10.0


def test_duration_bins_follow_the_edges():
    edges = [10, 60, 120]
    assert cubes.dur_bin([0.0, 9 / 60, 10 / 60, 59 / 60, 1.0, 1.99, 2.0, 30.0], edges).tolist() == [0, 0, 1, 1, 2, 2, 3, 3]


def test_session_files_have_no_ids_and_counts_add_up():
    P, ex, rec, ev = scenario()
    a = SS.attempts_table(P, ex, rec, ev)
    s = SS.participants_table(P, a, T0 + 70 * MIN, params(session_ref_min_n=1))
    inp = cubes.Inputs(P=P, events=ev, ex=ex, active=None, launch_ms=T0, p=params(), bin_minutes=15, attempts=a, sessions=s)
    st, tf, ah = cubes.session_state(inp), cubes.time_on_feed_hist(inp), cubes.attempts_hist(inp)
    assert st["n"].sum() == 4 and set(st["state"]) == {"done", "left", "stopped"}
    assert tf[tf["measure"] == "total"]["n"].sum() == 4 and tf[(tf["measure"] == "final_attempt") & (tf["group"] == "done")]["n"].sum() == 1
    assert ah["n"].sum() == len(a) and set(ah["ends_as"]) == {"done", "restarted", "incomplete", "cancelled"}
    assert round(tf[tf["measure"] == "total"]["sum_min"].sum(), 3) == round(s["total_min"].sum(), 3)
    for df in (st, tf, ah):
        assert not [c for c in df.columns if c in cubes.ID_LIKE]


def test_empty_inputs_give_empty_frames():
    inp = cubes.Inputs(P=pframe([]), events=events([]), ex=None, active=None, launch_ms=T0, p=params(), bin_minutes=15)
    for f in (cubes.session_state, cubes.time_on_feed_hist, cubes.attempts_hist):
        assert f(inp).empty


class FakeRecords:
    """record_entry as rows (record_id, user_id, attempt, ts); reads ranges like db.LiveSource."""
    def __init__(self, rows):
        self.rows = pd.DataFrame(rows, columns=["record_id", "user_id", "attempt", "ts"])
        self.calls = []

    def record_id_at(self, cc, t_ms):
        hit = self.rows[self.rows["ts"] >= t_ms]
        return int(hit["record_id"].min()) if len(hit) else None

    def record_id_max(self, cc):
        return int(self.rows["record_id"].max()) if len(self.rows) else None

    def record_attempts(self, cc, after_id, upto_id):
        self.calls.append((after_id, upto_id))
        r = self.rows[(self.rows["record_id"] > after_id) & (self.rows["record_id"] <= upto_id)]
        return r.groupby(["user_id", "attempt"])["ts"].agg(n_records="size", first_record_ms="min", last_record_ms="max").reset_index()


def stream(n, t0=T0):
    """n rows in time order: user 1 attempt 1, then a long gap, then user 1 attempt 2 and user 2."""
    rows = []
    for k in range(n):
        u, a = (1, 1) if k < n // 2 else (1, 2) if k % 2 else (2, 1)
        rows.append((k + 1, u, a, t0 + k * 1000))
    return rows


def as_dict(df):
    return {(int(r.user_id), int(r.attempt)): (int(r.n_records), int(r.first_record_ms), int(r.last_record_ms)) for r in df.itertuples()}


def test_incremental_equals_one_shot_and_picks_up_a_late_restart():
    rows = stream(40)
    full = detail.record_attempts(FakeRecords(rows), "UK", T0, {"rec_attempts": {}}, 1000)
    cache = {"rec_attempts": {}}
    src = FakeRecords(rows[:20])
    detail.record_attempts(src, "UK", T0, cache, 7)                           # first run in chunks of 7 ids
    assert len(src.calls) == 3 and src.calls[0][0] == 0
    src.rows = pd.DataFrame(rows, columns=src.rows.columns)                   # later: the rest, including attempt 2 after a gap
    again = detail.record_attempts(src, "UK", T0, cache, 7)
    assert as_dict(again) == as_dict(full)
    assert src.calls[-1][0] >= 20                                             # only the new ids were read


def test_first_run_resumes_after_a_stop():
    rows = stream(30)
    cache = {"rec_attempts": {}}
    src = FakeRecords(rows)
    saved = []

    def save():
        saved.append(cache["rec_attempts"]["UK"]["hwm"])
        if len(saved) == 2:
            raise TimeoutError("stopped")
    with pytest.raises(TimeoutError):
        detail.record_attempts(src, "UK", T0, cache, 5, save)
    assert saved == [5, 10]
    src.calls.clear()
    resumed = detail.record_attempts(src, "UK", T0, cache, 5, None)
    assert src.calls[0][0] == 10                                              # continued from the saved id
    assert as_dict(resumed) == as_dict(detail.record_attempts(FakeRecords(rows), "UK", T0, {"rec_attempts": {}}, 1000))


def test_changed_launch_resets_the_aggregates():
    cache = {"rec_attempts": {}}
    detail.record_attempts(FakeRecords(stream(10)), "UK", T0, cache, 100)
    out = detail.record_attempts(FakeRecords(stream(10, T0 + 5000)), "UK", T0 + 5000, cache, 100)
    assert cache["rec_attempts"]["UK"]["launch_ms"] == T0 + 5000 and len(out) >= 1


def test_ids_report_lists_short_stays_reasons_and_the_longest_restarting_attempt():
    P, ex, rec, ev = scenario()
    a = SS.attempts_table(P, ex, rec, ev)
    s = SS.participants_table(P, a, T0 + 70 * MIN, params(session_ref_min_n=1))
    ids_df = pd.DataFrame({"country": "UK", "user_id": [1, 2, 3], "yougov_id": ["vAAA", "vBBB", "vCCC"]}).merge(
        s[["country", "user_id", "condition", "status", "total_min", "n_attempts"]], on=["country", "user_id"])
    text = report.build_report(["vAAA", "vBBB", "vCCC", "vZZZ"], ids_df, a, s, "2026-11-25T12:00:00Z", [10, 60], ["PAGE_RELOAD_DETECTED", "IDLE_DETECTED"], s.attrs["reference"])
    assert "vZZZ" in text.split("no row for")[1].split("\n")[0]                # an id without a row is named
    sec60 = text.split("## Stayed less than 60 seconds")[1].split("## Stayed less than 10 seconds")[0]
    assert "vCCC" in sec60 and "vBBB" not in sec60 and "vAAA" not in sec60       # only user 3 (6 s) stayed under a minute in total
    sec10 = text.split("## Stayed less than 10 seconds")[1].split("## Restarting attempts")[0]
    assert "vCCC" in sec10 and "1 of 3 listed" in sec10 and "No restart among them" in sec10
    allr = text.split("## Restarting attempts of all listed participants")[1].split("## All participants")[0]
    assert "vBBB" in allr and "attempt 1" in allr                               # the only restarting attempt is attempt 1 of vBBB, 6 s


def test_ids_report_restart_reason_and_how():
    P, ex, rec, ev = scenario()
    a = SS.attempts_table(P, ex, rec, ev)
    s = SS.participants_table(P, a, T0 + 70 * MIN, params(session_ref_min_n=1))
    ids_df = pd.DataFrame({"country": "UK", "user_id": [2], "yougov_id": ["vBBB"]}).merge(
        s[["country", "user_id", "condition", "status", "total_min", "n_attempts"]], on=["country", "user_id"])
    text = report.build_report(["vBBB"], ids_df, a, s, "t", [120], ["PAGE_RELOAD_DETECTED"], None)   # total 1.7 min < 120 s
    sec = text.split("## Stayed less than 120 seconds")[1]
    assert "Restarted (two or more attempts): 1 of 1 (vBBB)" in sec
    assert "| PAGE_RELOAD_DETECTED | 1 | 1 |" in sec and "1 of 1 restarts follow a logged stop" in sec

"""Synthetic cases for classify.py (no study data in this public repo).
They mirror patterns seen in the 2026-11-20 pilot: idle restarts, reload after a duplicate
attempt, ignored NOT_FOUND codes, and sessions still running at the pull."""
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import classify as C  # noqa: E402

STOP = {"bot": "AUTOMATED_BROWSER_DETECTED", "idle": "IDLE_DETECTED",
        "reload": "PAGE_RELOAD_DETECTED"}
IGNORE = ["NOT_FOUND"]
MIN = 60_000
PULL = 1_000 * MIN  # pull time in epoch ms


def err(code, ts):
    return {"code": code, "detail": None, "timestamp_server": ts}


def make(rows):
    """rows: (id, created_at, done, cancelled, errors list or None)"""
    df = pd.DataFrame(rows, columns=["id", "created_at", "done", "cancelled", "errors"])
    df["errors"] = df["errors"].apply(lambda e: None if e is None else json.dumps(e))
    df["country"] = "UK"
    return df


def run(rows, session_min=15):
    v = make(rows)
    e = C.explode_errors(v, "UK")
    out = C.classify(v, e, PULL, session_min, IGNORE, STOP)
    return {u: (s, r) for u, s, r in zip(out["user_id"], out["status"], out["reason"])}


OLD = PULL - 60 * MIN  # created long before the pull


def test_done_wins_over_codes():
    got = run([(1, OLD, True, False, [err("IDLE_DETECTED", 10)])])
    assert got[1] == ("done", "done")


def test_cancel_reasons_each_code():
    got = run([(1, OLD, False, True, [err("AUTOMATED_BROWSER_DETECTED", 10)]),
               (2, OLD, False, True, [err("IDLE_DETECTED", 10)]),
               (3, OLD, False, True, [err("PAGE_RELOAD_DETECTED", 10)])])
    assert got == {1: ("cancelled", "bot"), 2: ("cancelled", "idle"), 3: ("cancelled", "reload")}


def test_cancel_reason_is_last_stop_by_timestamp_not_list_order():
    got = run([(1, OLD, False, True, [err("PAGE_RELOAD_DETECTED", 30),
                                      err("IDLE_DETECTED", 20)])])
    assert got[1] == ("cancelled", "reload")


def test_non_stop_codes_do_not_set_reason():
    got = run([(1, OLD, False, True, [err("DUPLICATE_PARTICIPATION_ATTEMPT", 10),
                                      err("PAGE_RELOAD_DETECTED", 20),
                                      err("DUPLICATE_PARTICIPATION_ATTEMPT", 30)]),
               (2, OLD, False, True, [err("DUPLICATE_PARTICIPATION_ATTEMPT", 10)]),
               (3, OLD, False, True, None)])
    assert got == {1: ("cancelled", "reload"), 2: ("cancelled", "other"),
                   3: ("cancelled", "other")}


def test_restart_after_idle_then_done_or_open():
    # idle restart resets cancelled to False and keeps the old error entry
    got = run([(1, OLD, True, False, [err("IDLE_DETECTED", 10)]),
               (2, OLD, False, False, [err("IDLE_DETECTED", 10)]),
               (3, OLD, False, True, [err("IDLE_DETECTED", 10), err("IDLE_DETECTED", 40)])])
    assert got == {1: ("done", "done"), 2: ("incomplete", "error_logged"),
                   3: ("cancelled", "idle")}


def test_ignored_codes_only_is_no_error():
    got = run([(1, OLD, False, False, [err("NOT_FOUND", 10)]),
               (2, OLD, False, False, [err("NOT_FOUND", 10), err("SOME_ERROR", 20)]),
               (3, OLD, False, False, None),
               (4, OLD, False, False, [])])
    assert got == {1: ("incomplete", "no_error"), 2: ("incomplete", "error_logged"),
                   3: ("incomplete", "no_error"), 4: ("incomplete", "no_error")}


def test_in_session_boundary_and_precedence():
    got = run([(1, PULL - 15 * MIN + 1, False, False, [err("SOME_ERROR", 10)]),  # 14.99 min
               (2, PULL - 15 * MIN, False, False, None),                          # exactly 15
               (3, PULL - 1 * MIN, True, False, None),                             # done is final
               (4, PULL - 1 * MIN, False, True, [err("IDLE_DETECTED", 10)])])      # cancelled too
    assert got == {1: ("incomplete", "in_session"), 2: ("incomplete", "no_error"),
                   3: ("done", "done"), 4: ("cancelled", "idle")}


def test_null_flags_count_as_false():
    got = run([(1, OLD, None, None, None)])
    assert got[1] == ("incomplete", "no_error")


def test_missing_timestamp_sorts_first():
    got = run([(1, OLD, False, True, [err("PAGE_RELOAD_DETECTED", 50),
                                      err("IDLE_DETECTED", None)])])
    assert got[1] == ("cancelled", "reload")


def test_same_user_id_in_two_countries_is_kept_apart():
    uk = make([(7, OLD, False, True, [err("IDLE_DETECTED", 10)])])
    de = make([(7, OLD, False, True, None)])
    de["country"] = "DE"
    v = pd.concat([uk, de], ignore_index=True)
    e = pd.concat([C.explode_errors(uk, "UK"), C.explode_errors(de, "DE")], ignore_index=True)
    out = C.classify(v, e, PULL, 15, IGNORE, STOP)
    got = {(c, s, r) for c, s, r in zip(out["country"], out["status"], out["reason"])}
    assert got == {("UK", "cancelled", "idle"), ("DE", "cancelled", "other")}


def test_one_row_per_participant_and_categories_cover_output():
    rows = [(i, OLD, i % 3 == 0, i % 3 == 1, None) for i in range(30)]
    v = make(rows)
    out = C.classify(v, C.explode_errors(v, "UK"), PULL, 15, IGNORE, STOP)
    assert len(out) == 30 and out["user_id"].is_unique
    assert set(zip(out["status"], out["reason"])) <= set(C.categories(STOP))


def test_empty_input():
    v = make([])
    out = C.classify(v, C.explode_errors(v, "UK"), PULL, 15, IGNORE, STOP)
    assert list(out.columns) == C.OUT_COLUMNS and out.empty

"""checks.py, spot.py, detail.py, db.py and config.py as pure units."""
import os
import sys

import numpy as np
import pandas as pd
import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import checks  # noqa: E402
import config as cfgmod  # noqa: E402
import cubes  # noqa: E402
import db  # noqa: E402
import detail  # noqa: E402
import outcomes  # noqa: E402
import spot  # noqa: E402
from tests.test_aggregate import make_cfg  # noqa: E402


def ex(rows):
    return pd.DataFrame(rows, columns=["country", "user_id", "endpoint", "algo_type", "timestamp_server", "request_index", "phase"])


def test_attempts_from_init_rows_and_from_the_attempt_column():
    e = ex([("UK", 1, "init", "A", 1, 0, None), ("UK", 1, "next_batch", "A", 2, 1, "warmup"),
            ("UK", 1, "init", "A", 3, 0, None), ("UK", 1, "next_batch", "A", 4, 1, "warmup")])
    s = checks.segment_attempts(e)
    assert s["final_attempt"].unique().tolist() == [2] and s["attempt_id"].tolist() == [1, 1, 2, 2]
    e2 = e.assign(attempt=[1, 1, 2, 2])
    s2 = checks.segment_attempts(e2, {("UK", 1): 2})
    assert s2["attempt_id"].tolist() == [1, 1, 2, 2] and s2["final_attempt"].unique().tolist() == [2]
    # a participant with a missing attempt number falls back to the init rows
    e3 = e.assign(attempt=[1, None, 2, 2])
    assert checks.segment_attempts(e3, {("UK", 1): 2})["attempt_id"].tolist() == [1, 1, 2, 2]


def test_flag_rules():
    ok = ex([("UK", 1, "init", "A", 1, 0, None), ("UK", 1, "next_batch", "ATTENTION", 2, 1, "warmup"), ("UK", 1, "next_batch", "ATTENTION", 3, 2, "algorithm")])
    assert not any(checks.integrity_flags("ATTENTION", 9, ok)[k] for k in checks.ALL_FLAGS)
    gap = ok.assign(request_index=[0, 1, 3])
    assert checks.integrity_flags("ATTENTION", 9, gap)["request_gap"]
    mism = ok.assign(algo_type=["A", "ATTENTION", "PREFERENCE"])
    assert checks.integrity_flags("ATTENTION", 9, mism)["condition_mismatch"]
    stuck = ok.assign(phase=[None, "warmup", "waiting"])
    assert checks.integrity_flags("ATTENTION", 9, stuck)["never_left_warmup"]
    assert not checks.integrity_flags("RANDOM", 9, stuck)["never_left_warmup"]
    # no phase stored: the algo_type rule is the fallback
    nophase = ok.assign(phase=None)
    assert not checks.integrity_flags("ATTENTION", 9, nophase)["never_left_warmup"]
    assert checks.integrity_flags("ATTENTION", 9, nophase.assign(algo_type="RANDOM"))["never_left_warmup"]
    assert checks.integrity_flags("ATTENTION", 0, ok)["no_records"]


def test_retook_after_stop_orders_stop_and_restart():
    P = pd.DataFrame({"country": ["UK"] * 3, "user_id": [1, 2, 3]})
    events = pd.DataFrame({"country": ["UK"] * 4, "user_id": [1, 1, 2, 3], "code": ["IDLE_DETECTED", "TIMELINE_RESTARTED", "TIMELINE_RESTARTED", "SERVER_ERROR"],
                           "timestamp_server": [10, 20, 20, 5]})
    got = checks.retook_after_stop(P, pd.Series([2, 2, 3]), events, ["IDLE_DETECTED"], {})
    assert got.tolist() == [True, False, False]   # 2 restarted without a stop; 3 had only a server error
    late = checks.retook_after_stop(P.iloc[:1], pd.Series([2]), events, ["IDLE_DETECTED"], {("UK", 1): 5})
    assert late.tolist() == [False]               # the stop (10) came after the final start (5)
    assert checks.retook_after_stop(P.iloc[:1], pd.Series([1]), events, ["IDLE_DETECTED"], {}).tolist() == [False]


def test_spot_default_pick_batches_and_nan():
    c = pd.DataFrame({"user_id": [1, 2, 3, 4], "condition": ["ATTENTION"] * 3 + ["RANDOM"], "created_at": [4, 3, 2, 1], "n_next_batch": [10, 12, 30, 11]})
    assert spot.pick_defaults(c, 10) == {"ATTENTION": 2, "RANDOM": 4}   # median 12, closest is user 2
    assert spot.pick_defaults(c, 10, "UK:3")["PREFERENCE"] == 3
    inv = pd.DataFrame({"country": "UK", "platform": "X", "text": ["t" * 10] * 3, **{d: [1, 2, 0] for d in spot.PROFILE_DIMS}}, index=["a", "b", "c"])
    rows = pd.DataFrame({"user_id": [1, 1], "endpoint": ["init", "next_batch"], "timestamp_server": [0, 60_000], "request_index": [0, 1],
                         "phase": [float("nan"), "warmup"], "draw": ["initial_feed", "recommend"], "n_batches_served": [2, 3],
                         "u_long": [[0, 0, 0, 0, 0], [0.5, None, 0, 0, 0]], "served_post_ids": [list("abcabcabca"), ["a", "z", "c"]],
                         "inventory_sha256": ["s", "s"]})
    posts = {}
    rec = spot.user_record(rows, inv, 5, 5, posts)
    assert [b["batch"] for e in rec["exchanges"] for b in e["batches"]] == [1, 2, 3]
    assert rec["exchanges"][0]["phase"] is None and rec["exchanges"][1]["u_long_sum"] == 0.5
    assert rec["exchanges"][1]["batches"][0]["post_ids"] == ["a", "c"] and rec["exchanges"][1]["batches"][0]["n_served"] == 3  # z is not in the inventory
    assert posts["a"]["sum"] == 5.0 and posts["a"]["text"] == "ttttt" and posts["a"]["cut"]
    import json
    json.dumps(rec, allow_nan=False)


def test_spot_dwell_goes_to_the_signalled_batch_and_u_long_norm():
    inv = pd.DataFrame({"country": "UK", "platform": "X", "text": ["t"] * 12, **{d: [1] * 12 for d in spot.PROFILE_DIMS}},
                       index=list("abcdefghijkl"))
    ids0, ids1 = list("abcdefghij"), list("klmno")[:2] + ["a", "b", "c"]          # init serves batches 1 and 2; request 1 serves batch 3
    rows = pd.DataFrame({
        "user_id": [1, 1, 1], "endpoint": ["init", "next_batch", "next_batch"], "timestamp_server": [0, 1000, 2000],
        "request_index": [0, 1, 2], "phase": [None, "warmup", "warmup"], "draw": ["initial_feed", "initial_feed", "recommend"],
        "n_batches_served": [2, 3, 4], "u_long": [[0] * 5, [0] * 5, [3, 4, 0, 0, None]],
        "served_post_ids": [ids0, ids1, ids1],
        "signal_post_ids": [[], list("abcde"), list("fghij")],                       # request 1 reports batch 1, request 2 batch 2
        "dwell_times": [[], [1000, 2000, 3000, 4000, None], [10, 20, 30, 40, 50]],
        "signal_batch": [None, 1, 2], "inventory_sha256": ["s"] * 3})
    rec = spot.user_record(rows, inv, 5, 50, {})
    by = {b["batch"]: b for e in rec["exchanges"] for b in e["batches"]}
    assert by[1]["dwell_ms"] == [1000.0, 2000.0, 3000.0, 4000.0, None]            # a missing dwell stays null
    assert by[2]["dwell_ms"] == [10.0, 20.0, 30.0, 40.0, 50.0]
    assert by[3]["dwell_ms"] == [None] * len(by[3]["post_ids"])                   # no later request reported batch 3
    assert rec["dwell_unmatched"] == 0
    last = rec["exchanges"][2]
    assert last["u_long_sum"] == 7.0 and abs(last["u_long_norm"] - 5.0) < 1e-12
    bad = rows.assign(signal_batch=[None, 3, 2], signal_post_ids=[[], list("fghij"), list("fghij")],
                      dwell_times=[[], [1, 2, 3, 4, 5], [10, 20, 30, 40, 50]])   # request 1 claims batch 3 with ids not in it
    rec = spot.user_record(bad, inv, 5, 50, {})
    assert rec["dwell_unmatched"] == 5 and all(d is None for d in {b["batch"]: b for e in rec["exchanges"] for b in e["batches"]}[3]["dwell_ms"])
    import json
    json.dumps(rec, allow_nan=False)


def test_record_counts_are_cached_once_final():
    class Src:
        calls = 0
        def record_counts(self, cc, thr):
            Src.calls += 1
            return {int(u): 7 for u in thr["user_id"]}
    thr = pd.DataFrame({"user_id": [1], "since_ms": [1000], "created_at": [1000], "final_start": [np.nan]})
    cache = {"records": {}, "active": {}}
    detail.count_records(Src(), "UK", thr, cache, 1000 + 5 * 60_000, 15)    # session may still write: not final
    detail.count_records(Src(), "UK", thr, cache, 1000 + 6 * 60_000, 15)
    assert Src.calls == 2
    detail.count_records(Src(), "UK", thr, cache, 1000 + 16 * 60_000, 15)   # counted 16 min after the start: final
    detail.count_records(Src(), "UK", thr, cache, 1000 + 30 * 60_000, 15)
    assert Src.calls == 3
    detail.count_records(Src(), "UK", thr.assign(since_ms=2000), cache, 1000 + 40 * 60_000, 15)   # a restart changes the bound
    assert Src.calls == 4


def test_every_sql_statement_is_a_select():
    for sql in db.ALL_SQL:
        db.assert_select(sql.format(attempt=""))
    for bad in ["DELETE FROM visited_users", "SELECT 1; DROP TABLE x", "update x set a=1", "EXPLAIN ANALYZE SELECT 1"]:
        with pytest.raises(ValueError):
            db.assert_select(bad)
    assert "participant_contact" not in " ".join(db.ALL_SQL)


def test_config_divisibility_rules(tmp_path):
    cfg = make_cfg(tmp_path)
    cfgmod.validate_params(cfg)
    import dataclasses
    def bad(**p): return dataclasses.replace(cfg, params={**cfg.params, **p})
    with pytest.raises(ValueError, match="divide BIN_MINUTES"):
        cfgmod.validate_params(bad(event_bin_minutes=4))
    with pytest.raises(ValueError, match="multiple of BIN_MINUTES"):
        cfgmod.validate_params(bad(flag_bin_minutes=50))
    with pytest.raises(ValueError, match="RECORDS_MAX"):
        cfgmod.validate_params(bad(records_max=50001))
    with pytest.raises(ValueError, match="DETAIL"):
        cfgmod.validate_params(bad(detail="all"))
    with pytest.raises(ValueError, match="SPOT_USER"):
        cfgmod.validate_params(bad(spot_user="UK-5"))
    with pytest.raises(ValueError, match="PULLED_AT"):
        cfgmod.validate_params(dataclasses.replace(cfg, source="export:/x", pulled_at=""))


def test_builders_handle_empty_inputs():
    P = pd.DataFrame(columns=["country", "user_id", "created_at", "created_bin", "status", "reason", "condition", "started", "viewed_posts", "starts", "after_stop", "has_server_error", "n_records", "requests"] + outcomes.COLUMNS)
    i = cubes.Inputs(P=P, events=pd.DataFrame(columns=["country", "user_id", "pos", "code", "detail", "timestamp_server", "ts"]), ex=None, active=None,
                     launch_ms=0, p=cfgmod.default_params(), bin_minutes=15)
    for spec in cubes.REGISTRY:
        out = spec.build(i)
        assert list(out.columns) == spec.columns and out.empty, spec.name

"""A tiny synthetic export (CC/window/table.parquet) and a config that replays it. No study data."""
import dataclasses
import json
import os

import pandas as pd

from tests.test_aggregate import LAUNCH_MS, MIN, make_cfg

T0 = LAUNCH_MS + 5 * MIN


def state(ri, phase=None, u=None, draw="recommend", nb=None, inv_sha="abc"):
    return json.dumps({"request_index": ri, "phase": phase, "draw": draw, "u_long": u or [0, 0, 0, 0, 0],
                       "n_batches_served": nb, "inventory": {"file_sha256": inv_sha}})


def ex_row(i, uid, endpoint, ts, ri, phase, algo="ATTENTION", served=None, nb=None, u=None):
    return {"id": i, "user_id": uid, "endpoint": endpoint, "algo_type": algo, "timestamp_server": ts,
            "algo_state": state(ri, phase, u, nb=nb), "served_post_ids": json.dumps(served or [])}


def write_export(folder, country="UK", exchanges=(), records=(), visited=()):
    d = os.path.join(folder, country, "20261125T000000Z_20261126T000000Z_participant")
    os.makedirs(d, exist_ok=True)
    pd.DataFrame(list(visited)).to_parquet(os.path.join(d, "visited_users.parquet"))
    pd.DataFrame(list(exchanges), columns=["id", "user_id", "endpoint", "algo_type", "timestamp_server",
                                          "algo_state", "served_post_ids"]).to_parquet(os.path.join(d, "algo_exchange.parquet"))
    pd.DataFrame(list(records), columns=["user_id", "timestamp_server"]).to_parquet(os.path.join(d, "record_entry.parquet"))


def vrow(uid, created, done, cancelled, cond, errors=None, viewed=20):
    return {"id": uid, "yougov_id": f"v{uid}", "created_at": created, "done": done, "cancelled": cancelled, "started": True,
            "condition": cond, "viewed_posts": viewed, "errors": json.dumps(errors) if errors else None}


def scenario(tmp_path, detail="full", countries=("UK",)):
    """UK: 1 normal done, 2 done retaker after an idle stop, 3 done without records or exchanges, 4 incomplete with
    errors. Returns the config; the run writes into tmp_path/out."""
    folder = str(tmp_path / "export")
    idle_ts, restart_ts = T0 + 2 * MIN, T0 + 3 * MIN
    visited = [
        vrow(1, T0, True, False, "ATTENTION"),
        vrow(2, T0 + MIN, True, False, "PREFERENCE", errors=[
            {"code": "IDLE_DETECTED", "timestamp_server": idle_ts, "detail": "focused 5 s"},
            {"code": "TIMELINE_RESTARTED", "timestamp_server": restart_ts, "detail": "attempt 2"}]),
        vrow(3, T0 + 2 * MIN, True, False, "RANDOM"),
        vrow(4, T0 + 3 * MIN, False, False, "ATTENTION", errors=[
            {"code": "SERVER_ERROR", "timestamp_server": T0 + 4 * MIN, "detail": "InternalServerError"},
            {"code": "CLIENT_TRACKING_SEND_FAILED", "timestamp_server": T0 + 4 * MIN, "detail": "HTTP 502 Bad Gateway https://x"},
            {"code": "NOT_FOUND", "timestamp_server": T0 + 5 * MIN, "detail": "/some/path"}]),
    ]
    ex = []
    i = 0
    def add(*a, **k):
        nonlocal i; i += 1; ex.append(ex_row(i, *a, **k))
    # user 1: init + 3 next_batch (phase warmup, then algorithm)
    add(1, "init", T0 + 1000, 0, None, served=list("abcdefghij"), nb=2)
    for k, ph in enumerate(["warmup", "algorithm", "algorithm"], start=1):
        add(1, "next_batch", T0 + 1000 + k * 10_000, k, ph, served=list("klmno")[:5], nb=2 + k, u=[0.5, 0, 0, 0, 0] if k > 1 else None)
    # user 2: two attempts; the first with 3 requests, the second with 2
    add(2, "init", T0 + MIN, 0, None, algo="PREFERENCE", nb=2)
    add(2, "next_batch", T0 + MIN + 5_000, 1, "warmup", algo="PREFERENCE", nb=3)
    add(2, "init", restart_ts + 2000, 0, None, algo="PREFERENCE", nb=2)
    add(2, "next_batch", restart_ts + 12_000, 1, "warmup", algo="PREFERENCE", nb=3)
    # user 4 (incomplete): one init
    add(4, "init", T0 + 3 * MIN + 500, 0, None, nb=2)
    recs = ([(1, T0 + 2000 + k) for k in range(5)]
            + [(2, T0 + MIN + 100 + k) for k in range(3)] + [(2, restart_ts + 5000 + k) for k in range(4)])
    write_export(folder, "UK", ex, recs, visited)
    cfg = make_cfg(tmp_path, countries=list(countries), creds_keys={"UK": "uk_database", "DE": "ger_database"})
    if "DE" in countries:
        write_export(folder, "DE", [], [], [vrow(9, T0, False, False, "RANDOM")])
    cfg = dataclasses.replace(cfg, source=f"export:{folder}", pulled_at="2026-11-25T10:00:00Z",
                              params={**cfg.params, "detail": detail})
    return cfg

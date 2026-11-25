"""The published files end to end on a synthetic export: values, schema guards, failure domains."""
import json
import os
import sys

import pandas as pd
import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import aggregate  # noqa: E402
import cubes  # noqa: E402
from tests.helpers import scenario  # noqa: E402


def read(cfg, name):
    return pd.read_csv(os.path.join(cfg.outdir, name))


@pytest.fixture
def run_full(tmp_path):
    cfg = scenario(tmp_path)
    return cfg, aggregate.run(cfg)


def test_flags_are_counted_on_the_final_attempt(run_full):
    cfg, res = run_full
    f = read(cfg, "flags.csv")
    assert f["n_done"].sum() == 3
    # user 3 has no records, no init and no next_batch; the retaker's request_index restarts at 0 but is judged on its last attempt
    assert f[["no_records", "no_init", "no_next_batch"]].sum().tolist() == [1, 1, 1]
    assert f["request_gap"].sum() == 0 and f["condition_mismatch"].sum() == 0


def test_records_of_the_final_attempt_only(run_full):
    cfg, _ = run_full
    h = read(cfg, "records_hist.csv").groupby("records_bin")["n"].sum().to_dict()
    assert h == {0: 1, 1: 2}  # user 3: 0 rows; users 1 (5 rows) and 2 (4 rows of the final attempt) in [1, 2000)


def test_attempts_and_retook_after_stop(run_full):
    cfg, _ = run_full
    a = read(cfg, "attempts.csv")
    got = {(r.attempts, r.after_stop): r.n for r in a.groupby(["attempts", "after_stop"])["n"].sum().reset_index().itertuples()}
    assert got == {(1, 0): 2, (2, 1): 1, (0, 0): 1}  # user 3 has no init: no recorded start


def test_error_files_publish_only_clean_details(run_full):
    cfg, _ = run_full
    e = read(cfg, "errors_time.csv")
    assert set(zip(e["code"], e["detail"])) == {("SERVER_ERROR", "InternalServerError"), ("CLIENT_TRACKING_SEND_FAILED", "HTTP 502")}
    flow = read(cfg, "error_flow.csv")
    assert "NOT_FOUND" in set(flow["to_node"])  # FLOW_EXCLUDE_CODES is empty


def test_every_registry_file_has_its_columns_and_no_id(run_full):
    cfg, res = run_full
    assert set(res["files"]) == set(cubes.FILE_NAMES)
    for spec in cubes.REGISTRY:
        df = read(cfg, spec.name)
        assert list(df.columns) == spec.columns
        assert not set(df.columns) & set(cubes.ID_LIKE), spec.name
        assert (df.select_dtypes("number") >= 0).all().all() or spec.name == "requests_diff_hist.csv"
        # a participant time is never finer than its bin
        if spec.window == "created":
            t = pd.to_datetime(df["bin_start"], utc=True)
            assert ((t - pd.Timestamp("2026-11-25T08:30Z")).dt.total_seconds() % (cfg.bin_minutes * 60) == 0).all()


def test_meta_lists_files_params_and_coverage(run_full):
    cfg, res = run_full
    m = res["meta"]
    assert set(m["files"]) == set(cubes.FILE_NAMES) and m["params"]["batch_size"] == 5 and m["detail"]["UK"]["status"] == "ok"
    assert all("UK" in v["as_of"] for v in m["files"].values())
    assert "participant" not in json.dumps(m["params"])


def test_detail_off_publishes_core_files_only(tmp_path):
    cfg = scenario(tmp_path, detail="off")
    res = aggregate.run(cfg)
    core = {s.name for s in cubes.REGISTRY if s.coverage == "core"}
    assert set(res["files"]) == core
    assert res["meta"]["detail"]["UK"]["status"] == "off" and res["spot"] == "off"


def test_detail_failure_keeps_core_and_previous_detail_rows(tmp_path):
    cfg = scenario(tmp_path)
    first = aggregate.run(cfg)
    data = os.path.join(cfg.site_dir, "data"); os.makedirs(data, exist_ok=True)
    for name in list(first["files"]) + ["meta.json"]:
        src = first["meta_path"] if name == "meta.json" else first["files"][name]
        open(os.path.join(data, name), "w").write(open(src).read())
    import detail as D
    orig = D.run_country
    D.run_country = lambda *a, **k: (_ for _ in ()).throw(TimeoutError("statement timeout"))
    try:
        second = aggregate.run(cfg)
    finally:
        D.run_country = orig
    assert second["detail_status"] == {"UK": "failed"} and "UK" in second["detail_errors"]
    assert second["meta"]["detail"]["UK"]["as_of"] == first["meta"]["pulled_at"]
    assert (read(cfg, "flags.csv")["n_done"].sum() == 3)   # last published detail rows carried over
    assert second["meta"]["files"]["status_bins.csv"]["as_of"]["UK"] == second["meta"]["pulled_at"]


def test_spot_file_is_local_and_never_in_the_publish_list(tmp_path):
    import publish
    cfg = scenario(tmp_path)
    res = aggregate.run(cfg)
    assert "spot_users.json" not in publish.DATA_FILES and "participants.csv" not in publish.DATA_FILES
    assert "spot_users.json" not in res["files"] and "participants.csv" not in res["files"]
    with pytest.raises(publish.PublishError):
        publish.publish(cfg, {"spot_users.json": "x"}, res["meta_path"], "t", warn=lambda m: None)

"""The published files end to end on a synthetic export: values, schema guards, failure domains."""
import dataclasses
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


def spot_cfg(tmp_path, publish_spot="on"):
    """scenario with an inventory file that has the posts of the exchanges (a to o), so that the spot file is written."""
    inv = pd.DataFrame({"post_id": list("abcdefghijklmno"), "country": "UK", "platform": "X", "text": "t",
                        **{d: 1 for d in ["us_v_them", "fear", "outrage", "pride", "hope"]}})
    path = str(tmp_path / "inventory.parquet")
    inv.to_parquet(path)
    cfg = scenario(tmp_path)
    return dataclasses.replace(cfg, inventory_file=path, params={**cfg.params, "spot_publish": publish_spot, "spot_min_requests": 1})


def test_spot_file_is_published_only_when_on_and_only_with_the_listed_names(tmp_path):
    import publish
    res = aggregate.run(spot_cfg(tmp_path))
    assert "participants.csv" not in publish.DATA_FILES and "history" not in publish.DATA_FILES
    assert "participants.csv" not in res["files"] and res["remove"] == []
    assert "spot_users.json" in res["files"] and res["meta"]["spot"]["n_users"] >= 1
    assert res["meta"]["spot"]["as_of"] == res["meta"]["pulled_at"]
    (tmp_path / "off").mkdir()
    off = aggregate.run(spot_cfg(tmp_path / "off", "off"))
    assert "spot_users.json" not in off["files"] and off["remove"] == ["spot_users.json"] and off["meta"]["spot"] is None
    with pytest.raises(publish.PublishError):
        publish.publish(spot_cfg(tmp_path), {"participants.csv": "x"}, res["meta_path"], "t", warn=lambda m: None)


def test_published_spot_copy_is_kept_when_a_run_has_none_and_removed_when_off(tmp_path):
    import publish, subprocess
    cfg = spot_cfg(tmp_path)
    site = cfg.site_dir
    for a in (["init", "-q", "-b", "main"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
              ["commit", "-q", "--allow-empty", "-m", "init"]):
        subprocess.run(["git", "-C", site, *a], check=True)
    res = aggregate.run(cfg)
    publish.git(site, "remote", "add", "origin", str(tmp_path / "remote.git"))
    subprocess.run(["git", "init", "-q", "--bare", str(tmp_path / "remote.git")], check=True)
    publish.publish(cfg, res["files"], res["meta_path"], "t1", warn=lambda m: None, remove=res["remove"])
    assert os.path.isfile(os.path.join(site, "data", "spot_users.json"))
    # a run without INVENTORY_FILE writes no spot file: the published copy and its meta entry stay
    no_inv = dataclasses.replace(cfg, inventory_file="")
    second = aggregate.run(no_inv)
    assert "spot_users.json" not in second["files"] and second["meta"]["spot"] == res["meta"]["spot"]
    publish.publish(no_inv, second["files"], second["meta_path"], "t2", warn=lambda m: None, remove=second["remove"])
    assert os.path.isfile(os.path.join(site, "data", "spot_users.json"))
    # SPOT_PUBLISH off removes it
    off = dataclasses.replace(cfg, params={**cfg.params, "spot_publish": "off"})
    third = aggregate.run(off)
    publish.publish(off, third["files"], third["meta_path"], "t3", warn=lambda m: None, remove=third["remove"])
    assert not os.path.exists(os.path.join(site, "data", "spot_users.json"))


def test_detail_skips_countries_not_pulled(tmp_path):
    cfg = dataclasses.replace(scenario(tmp_path, "full", countries=("UK", "DE")), pull_countries=["UK"])
    res = aggregate.run(cfg)
    assert res["detail_status"] == {"UK": "ok", "DE": "not_pulled"}
    assert res["meta"]["countries"]["DE"]["status"] == "not_pulled" and res["meta"]["detail"]["DE"]["status"] == "not_pulled"

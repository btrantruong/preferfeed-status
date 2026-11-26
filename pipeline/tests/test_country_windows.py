"""A later launch and an end per country: ended countries, active participants and carried spot users."""
import dataclasses
import json
import os
import shutil

import pandas as pd
import pytest

import aggregate
import config as cfgmod
import detail
from tests.helpers import scenario, vrow, write_export
from tests.test_aggregate import LAUNCH_MS, MIN, fake_reader, make_cfg, publish_locally, visited, write_configs
from tests.test_panels import spot_cfg

END_UK = "2026-11-25T10:30"          # Europe/Berlin = 09:30Z, one hour after the launch
END_UK_MS = LAUNCH_MS + 60 * MIN
TABLES = {"UK": visited([(1, LAUNCH_MS + MIN, True, False, None)]),
          "DE": visited([(5, LAUNCH_MS + MIN, True, False, None)])}


def test_config_end_by_country(tmp_path):
    pipe = tmp_path / "site" / "pipeline"
    pipe.mkdir(parents=True)
    (tmp_path / "pfda" / "preferfeed_dataaccess").mkdir(parents=True)
    write_configs(pipe, f"MACHINE=t\nPFDA_DIR={tmp_path}/pfda\nCREDS={tmp_path}/creds.yml\nOUTDIR={tmp_path}/out\n")
    cfg = cfgmod.load(str(pipe), ["END_BY_COUNTRY=uk:" + END_UK])
    assert cfg.end_by_country == {"UK": END_UK} and cfg.ended == []
    assert cfg.ended_at(END_UK_MS - 1) == [] and cfg.ended_at(END_UK_MS) == ["UK"]
    with pytest.raises(ValueError, match="END_BY_COUNTRY"):
        cfgmod.load(str(pipe), ["END_BY_COUNTRY=XX:" + END_UK])
    with pytest.raises(ValueError, match="not after its launch"):
        cfgmod.load(str(pipe), ["END_BY_COUNTRY=DE:" + END_UK, "LAUNCH_BY_COUNTRY=DE:2026-11-26T10:00"])


def test_ended_country_is_pulled_before_its_end_and_not_after(tmp_path):
    cfg = make_cfg(tmp_path, end_by_country={"UK": END_UK})
    first = aggregate.run(cfg, END_UK_MS - MIN, fake_reader(TABLES))
    assert first["ended"] == [] and first["meta"]["countries"]["UK"]["status"] == "ok"
    publish_locally(cfg)
    second = aggregate.run(cfg, END_UK_MS, fake_reader({"DE": TABLES["DE"]}))    # a UK query would raise KeyError
    m = second["meta"]["countries"]
    assert second["ended"] == ["UK"] and second["failures"] == {}
    assert m["UK"]["status"] == "not_pulled" and m["UK"]["as_of"] == first["meta"]["pulled_at"]
    bins = pd.read_csv(os.path.join(cfg.outdir, "status_bins.csv"))
    assert bins.loc[bins["country"] == "UK", "n"].sum() == 1


def test_end_wins_over_pull_countries(tmp_path):
    cfg = make_cfg(tmp_path, end_by_country={"UK": END_UK}, pull_countries=["UK"])
    with pytest.raises(aggregate.NoDataError, match="no country to pull"):
        aggregate.run(cfg, END_UK_MS, fake_reader(TABLES))
    assert not os.path.exists(os.path.join(cfg.outdir, "status_bins.csv"))


def test_all_ended_writes_nothing(tmp_path):
    cfg = make_cfg(tmp_path, end_by_country={"UK": END_UK, "DE": END_UK})
    with pytest.raises(aggregate.NoDataError, match="no country to pull"):
        aggregate.run(cfg, END_UK_MS, fake_reader(TABLES))
    assert not os.path.exists(os.path.join(cfg.outdir, "status_bins.csv"))


def test_active_counts_only_participants_created_since_the_launch(tmp_path):
    cfg = scenario(tmp_path)
    folder = cfg.source[len("export:"):]
    launch = LAUNCH_MS + 30 * MIN
    visitors = [vrow(1, launch - MIN, False, False, "RANDOM"), vrow(2, launch, False, False, "RANDOM")]
    records = [(1, launch + MIN), (2, launch + MIN)]      # user 1 started before the launch and still sends records
    shutil.rmtree(os.path.join(folder, "UK"))
    write_export(folder, "UK", [], records, visitors)
    source, _ = aggregate.make_source(cfg)
    out = detail.active_bins(source, "UK", LAUNCH_MS, 5 * MIN, {"active": {}}, launch + 60 * MIN, 15, first_ms=launch)
    assert out.values.tolist() == [[launch, 1]]


def publish_spot(cfg, res):
    data = os.path.join(cfg.site_dir, "data")
    os.makedirs(data, exist_ok=True)
    for name, src in list(res["files"].items()) + [("meta.json", res["meta_path"])]:
        shutil.copyfile(src, os.path.join(data, name))


def load_spot(cfg):
    with open(os.path.join(cfg.outdir, "spot_users.json")) as fh:
        return json.load(fh)


def two_country_spot(tmp_path):
    """First run with UK pulled and published; then a config where UK has ended and DE has nobody done."""
    cfg = spot_cfg(tmp_path)
    folder = cfg.source[len("export:"):]
    write_export(folder, "DE", [], [], [vrow(9, LAUNCH_MS + MIN, False, False, "RANDOM")])
    cfg = dataclasses.replace(cfg, countries=["UK", "DE"])
    first = aggregate.run(cfg)
    publish_spot(cfg, first)
    published = load_spot(cfg)
    later = dataclasses.replace(cfg, end_by_country={"UK": "2026-11-25T10:00"}, pulled_at="2026-11-25T10:30:00Z")
    return later, first, published


def test_spot_users_of_an_ended_country_are_carried(tmp_path):
    cfg, first, published = two_country_spot(tmp_path)
    res = aggregate.run(cfg)
    now = load_spot(cfg)
    assert res["ended"] == ["UK"] and published["users"]
    assert now["users"] == published["users"] and now["posts"] == published["posts"]
    assert now["inventory"] == published["inventory"]
    assert res["meta"]["spot"]["n_users"] == len(published["users"]) and "spot_users.json" in res["files"]


def test_spot_users_are_carried_with_publishing_off(tmp_path):
    cfg, first, published = two_country_spot(tmp_path)
    os.remove(os.path.join(cfg.site_dir, "data", "spot_users.json"))       # publish.py removes it when off
    off = dataclasses.replace(cfg, params={**cfg.params, "spot_publish": "off"})
    for _ in range(2):                                                      # carried again from the carried file
        aggregate.run(off)
        assert load_spot(off)["users"] == published["users"]
    with open(os.path.join(off.outdir, "spot_users_full.json")) as fh:
        full = json.load(fh)
    assert all("u_long" in e for u in full["users"] for e in u["exchanges"])     # no field is lost in the full file


def test_spot_users_come_from_the_published_copy_in_a_new_output_folder(tmp_path):
    cfg, first, published = two_country_spot(tmp_path)
    new = dataclasses.replace(cfg, outdir=str(tmp_path / "new_out"))
    aggregate.run(new)
    assert load_spot(new)["users"] == published["users"]


def test_spot_users_created_before_the_launch_are_dropped(tmp_path):
    cfg, first, published = two_country_spot(tmp_path)
    cfg = dataclasses.replace(cfg, launch_by_country={"UK": "2026-11-25T09:45"})
    res = aggregate.run(cfg)
    now = load_spot(cfg)
    assert now["users"] == [] and now["posts"] == {}
    assert res["meta"]["spot"]["n_users"] == 0 and "spot_users.json" in res["files"]   # replaces the published copy

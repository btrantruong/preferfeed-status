"""aggregate.run end to end with a fake reader (no DB), plus the config guards."""
import json
import os
import sys

import pandas as pd
import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import aggregate  # noqa: E402
import config as cfgmod  # noqa: E402

MIN = 60_000
LAUNCH = "2026-11-25T09:30"          # Europe/Berlin = 08:30Z
LAUNCH_MS = pd.Timestamp("2026-11-25T08:30Z").value // 1_000_000


def fake_reader(tables, fail=()):
    """tables: {country: DataFrame of visited_users rows}; countries in fail raise."""
    class FakeReader:
        def __init__(self, path=None, countries=None, engines=None):
            self.engines = engines or {}

        def get_engine(self, cfg):
            return cfg["name"]

        def get_table_subset(self, country, table, start, end, by, tz):
            if country in fail:
                raise ConnectionError(f"{country} down")
            df = tables[country].copy()
            lo = aggregate.launch_ms(start, tz)
            hi = pd.Timestamp(end).value // 1_000_000
            return df[(df["created_at"] >= lo) & (df["created_at"] < hi)]
    return FakeReader


def make_cfg(tmp_path, **kw):
    site = tmp_path / "site"
    (site / "pipeline").mkdir(parents=True, exist_ok=True)
    creds = tmp_path / "creds.yml"
    creds.write_text("uk_database: {name: uk}\nger_database: {name: de}\n")
    base = dict(launch=LAUNCH, tz="Europe/Berlin", countries=["UK", "DE"],
                creds_keys={"UK": "uk_database", "DE": "ger_database"}, bin_minutes=15,
                session_min=15, ignore_codes=["NOT_FOUND"],
                stop_codes={"bot": "AUTOMATED_BROWSER_DETECTED", "idle": "IDLE_DETECTED",
                            "reload": "PAGE_RELOAD_DETECTED"},
                idle_min_seconds=360, idle_min_posts=20, stale_after_min=None, refresh_min=2,
                connect_timeout_s=5, min_push_gap_min=6, scripts_url="x", git_remote="origin",
                git_branch="main", machine="test", pfda_dir=str(tmp_path), creds=str(creds),
                outdir=str(tmp_path / "out"), site_dir=str(site))
    base.update(kw)
    return cfgmod.Config(**base)


def visited(rows):
    return pd.DataFrame(rows, columns=["id", "created_at", "done", "cancelled", "errors"])


def test_bins_start_at_launch_and_exclude_before(tmp_path):
    cfg = make_cfg(tmp_path)
    uk = visited([(1, LAUNCH_MS - 1, True, False, None),        # before launch: excluded
                  (2, LAUNCH_MS, True, False, None),            # first bin
                  (3, LAUNCH_MS + 14 * MIN, False, False, None),
                  (4, LAUNCH_MS + 15 * MIN, False, True, None)])
    de = visited([])
    pulled = LAUNCH_MS + 60 * MIN
    res = aggregate.run(cfg, pulled, fake_reader({"UK": uk, "DE": de}))
    bins = pd.read_csv(os.path.join(cfg.outdir, "status_bins.csv"))
    got = set(zip(bins["bin_start"], bins["status"], bins["reason"], bins["n"]))
    assert got == {("2026-11-25T08:30:00Z", "done", "done", 1),
                   ("2026-11-25T08:30:00Z", "incomplete", "no_error", 1),
                   ("2026-11-25T08:45:00Z", "cancelled", "other", 1)}
    meta = res["meta"]
    assert meta["launch"] == "2026-11-25T09:30:00+01:00" and meta["countries"]["UK"]["n"] == 3
    assert meta["countries"]["DE"] == {"status": "ok", "as_of": meta["pulled_at"], "n": 0,
                                       "launch_utc": "2026-11-25T08:30:00Z"}
    assert os.path.isfile(os.path.join(cfg.outdir, "participants.csv"))
    hist = pd.read_csv(os.path.join(cfg.outdir, "history", "status_bins_history.csv"))
    assert set(hist["machine"]) == {"test"} and len(hist) == len(bins)


def publish_locally(cfg):
    data = os.path.join(cfg.site_dir, "data")
    os.makedirs(data, exist_ok=True)
    for name in ["status_bins.csv", "meta.json"]:
        with open(os.path.join(cfg.outdir, name)) as src, open(os.path.join(data, name), "w") as dst:
            dst.write(src.read())


def test_failed_country_keeps_previous_bins_and_as_of(tmp_path):
    cfg = make_cfg(tmp_path)
    uk = visited([(1, LAUNCH_MS + MIN, True, False, None)])
    de = visited([(5, LAUNCH_MS + MIN, False, True, None)])
    first = aggregate.run(cfg, LAUNCH_MS + 30 * MIN, fake_reader({"UK": uk, "DE": de}))
    publish_locally(cfg)
    uk2 = visited([(1, LAUNCH_MS + MIN, True, False, None), (2, LAUNCH_MS + 20 * MIN, True, False, None)])
    second = aggregate.run(cfg, LAUNCH_MS + 40 * MIN,
                           fake_reader({"UK": uk2, "DE": de}, fail={"DE"}))
    m = second["meta"]["countries"]
    assert m["DE"]["status"] == "failed" and m["DE"]["as_of"] == first["meta"]["pulled_at"]
    assert m["UK"]["n"] == 2 and "DE" in second["failures"]
    bins = pd.read_csv(os.path.join(cfg.outdir, "status_bins.csv"))
    assert bins.loc[bins["country"] == "DE", "n"].sum() == 1
    assert bins.loc[bins["country"] == "UK", "n"].sum() == 2


def test_no_carry_over_when_launch_changed(tmp_path):
    cfg = make_cfg(tmp_path)
    tables = {"UK": visited([(1, LAUNCH_MS + MIN, True, False, None)]),
              "DE": visited([(5, LAUNCH_MS + MIN, True, False, None)])}
    aggregate.run(cfg, LAUNCH_MS + 30 * MIN, fake_reader(tables))
    publish_locally(cfg)
    cfg2 = make_cfg(tmp_path, launch="2026-11-25T09:00")
    res = aggregate.run(cfg2, LAUNCH_MS + 40 * MIN, fake_reader(tables, fail={"DE"}))
    assert res["meta"]["countries"]["DE"]["as_of"] is None
    bins = pd.read_csv(os.path.join(cfg2.outdir, "status_bins.csv"))
    assert "DE" not in set(bins["country"])


def test_all_failed_raises_and_writes_nothing(tmp_path):
    cfg = make_cfg(tmp_path)
    tables = {"UK": visited([]), "DE": visited([])}
    with pytest.raises(aggregate.NoDataError):
        aggregate.run(cfg, LAUNCH_MS, fake_reader(tables, fail={"UK", "DE"}))
    assert not os.path.exists(os.path.join(cfg.outdir, "status_bins.csv"))


def test_before_launch_is_empty_not_error(tmp_path):
    cfg = make_cfg(tmp_path)
    tables = {"UK": visited([(1, LAUNCH_MS - MIN, True, False, None)]), "DE": visited([])}
    res = aggregate.run(cfg, LAUNCH_MS - 10 * MIN, fake_reader(tables))
    bins = pd.read_csv(os.path.join(cfg.outdir, "status_bins.csv"))
    assert bins.empty and res["meta"]["countries"]["UK"]["n"] == 0


def write_configs(pipeline_dir, local):
    shared = os.path.join(os.path.dirname(HERE), "pipeline", "config.env")
    with open(shared) as fh:
        (pipeline_dir / "config.env").write_text(fh.read())
    (pipeline_dir / "config.local.env").write_text(local)


def test_config_rejects_outdir_inside_repo(tmp_path):
    site = tmp_path / "site"
    pipe = site / "pipeline"
    pipe.mkdir(parents=True)
    (tmp_path / "pfda" / "preferfeed_dataaccess").mkdir(parents=True)
    write_configs(pipe, f"MACHINE=t\nPFDA_DIR={tmp_path}/pfda\nCREDS={tmp_path}/creds.yml\n"
                        f"OUTDIR={site}/out\n")
    with pytest.raises(ValueError, match="inside the site repo"):
        cfgmod.load(str(pipe))
    write_configs(pipe, f"MACHINE=t\nPFDA_DIR={tmp_path}/pfda\nCREDS={tmp_path}/creds.yml\n"
                        f"OUTDIR={tmp_path}/out\n")
    cfg = cfgmod.load(str(pipe), ["LAUNCH=2026-11-20T14:00"])
    assert cfg.launch == "2026-11-20T14:00" and cfg.bin_minutes == 15 and cfg.stale_after_min is None
    with pytest.raises(ValueError, match="unknown --set"):
        cfgmod.load(str(pipe), ["LUNCH=1"])


# ---- pulling some countries only, launching countries at different times -------------------------------
def test_not_pulled_country_is_never_queried_and_keeps_its_published_rows(tmp_path):
    cfg = make_cfg(tmp_path)
    tables = {"UK": visited([(1, LAUNCH_MS + MIN, True, False, None)]),
              "DE": visited([(5, LAUNCH_MS + MIN, False, True, None)])}
    first = aggregate.run(cfg, LAUNCH_MS + 30 * MIN, fake_reader(tables))
    publish_locally(cfg)
    cfg2 = make_cfg(tmp_path, pull_countries=["UK"])
    uk_only = {"UK": visited([(1, LAUNCH_MS + MIN, True, False, None), (2, LAUNCH_MS + 20 * MIN, True, False, None)])}
    second = aggregate.run(cfg2, LAUNCH_MS + 40 * MIN, fake_reader(uk_only))   # DE table absent: a query would raise KeyError
    m = second["meta"]["countries"]
    assert m["DE"]["status"] == "not_pulled" and m["DE"]["n"] is None
    assert m["DE"]["as_of"] == first["meta"]["pulled_at"] and m["UK"]["n"] == 2
    assert second["failures"] == {}
    bins = pd.read_csv(os.path.join(cfg2.outdir, "status_bins.csv"))
    assert bins.loc[bins["country"] == "DE", "n"].sum() == 1
    assert second["detail_status"]["DE"] == "not_pulled"
    table = aggregate.summary_table(second)
    assert table.loc[table["country"] == "DE", "n"].isna().all()


def test_country_never_pulled_is_listed_without_data(tmp_path):
    cfg = make_cfg(tmp_path, pull_countries=["UK"])
    res = aggregate.run(cfg, LAUNCH_MS + 30 * MIN, fake_reader({"UK": visited([(1, LAUNCH_MS + MIN, True, False, None)])}))
    assert res["meta"]["countries"]["DE"] == {"status": "not_pulled", "as_of": None, "n": None,
                                              "launch_utc": "2026-11-25T08:30:00Z"}
    bins = pd.read_csv(os.path.join(cfg.outdir, "status_bins.csv"))
    assert set(bins["country"]) == {"UK"}


def test_country_launch_filters_that_country_only(tmp_path):
    cfg = make_cfg(tmp_path, launch_by_country={"DE": "2026-11-25T10:00"})     # DE launches 30 min after UK
    de_launch = LAUNCH_MS + 30 * MIN
    tables = {"UK": visited([(1, LAUNCH_MS + 10 * MIN, True, False, None)]),
              "DE": visited([(5, LAUNCH_MS + 10 * MIN, True, False, None),     # before DE launch: excluded
                             (6, de_launch, True, False, None),
                             (7, de_launch + 20 * MIN, False, True, None)])}
    res = aggregate.run(cfg, LAUNCH_MS + 90 * MIN, fake_reader(tables))
    m = res["meta"]["countries"]
    assert m["UK"]["launch_utc"] == "2026-11-25T08:30:00Z" and m["DE"]["launch_utc"] == "2026-11-25T09:00:00Z"
    assert m["UK"]["n"] == 1 and m["DE"]["n"] == 2
    assert res["meta"]["launch_utc"] == "2026-11-25T08:30:00Z"   # the axis starts at the earliest launch
    bins = pd.read_csv(os.path.join(cfg.outdir, "status_bins.csv"))
    de = bins[bins["country"] == "DE"]
    assert set(de["bin_start"]) == {"2026-11-25T09:00:00Z", "2026-11-25T09:15:00Z"}


def test_changed_country_launch_resets_only_that_country(tmp_path):
    cfg = make_cfg(tmp_path, launch_by_country={"DE": "2026-11-25T10:00"})
    de_launch = LAUNCH_MS + 30 * MIN
    tables = {"UK": visited([(1, LAUNCH_MS + MIN, True, False, None)]),
              "DE": visited([(6, de_launch, True, False, None)])}
    aggregate.run(cfg, LAUNCH_MS + 60 * MIN, fake_reader(tables))
    publish_locally(cfg)
    cfg2 = make_cfg(tmp_path, launch_by_country={"DE": "2026-11-25T10:30"}, pull_countries=["UK"])
    res = aggregate.run(cfg2, LAUNCH_MS + 90 * MIN, fake_reader({"UK": tables["UK"]}))
    assert res["meta"]["countries"]["DE"]["as_of"] is None                 # its published rows are not carried
    cfg3 = make_cfg(tmp_path, launch_by_country={"DE": "2026-11-25T10:00"}, pull_countries=["UK"])
    res = aggregate.run(cfg3, LAUNCH_MS + 90 * MIN, fake_reader({"UK": tables["UK"]}))
    assert res["meta"]["countries"]["DE"]["as_of"] is not None             # same launch: carried


def test_config_pull_countries_and_country_launch(tmp_path):
    site = tmp_path / "site"
    pipe = site / "pipeline"
    pipe.mkdir(parents=True)
    (tmp_path / "pfda" / "preferfeed_dataaccess").mkdir(parents=True)
    write_configs(pipe, f"MACHINE=t\nPFDA_DIR={tmp_path}/pfda\nCREDS={tmp_path}/creds.yml\nOUTDIR={tmp_path}/out\n")
    cfg = cfgmod.load(str(pipe))
    assert cfg.pulled_countries() == cfg.countries and cfg.launch_of("DE") == cfg.launch
    cfg = cfgmod.load(str(pipe), ["PULL_COUNTRIES=uk", "LAUNCH_BY_COUNTRY=DE:2026-11-27T10:00"])
    assert cfg.pulled_countries() == ["UK"] and cfg.launch_of("DE") == "2026-11-27T10:00" and cfg.launch_of("UK") == cfg.launch
    with pytest.raises(ValueError, match="PULL_COUNTRIES"):
        cfgmod.load(str(pipe), ["PULL_COUNTRIES=XX"])
    with pytest.raises(ValueError, match="before LAUNCH"):
        cfgmod.load(str(pipe), ["LAUNCH_BY_COUNTRY=DE:2026-11-24T10:00"])
    with pytest.raises(ValueError, match="LAUNCH_BY_COUNTRY"):
        cfgmod.load(str(pipe), ["LAUNCH_BY_COUNTRY=XX:2026-11-27T10:00"])

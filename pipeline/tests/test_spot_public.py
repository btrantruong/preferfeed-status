"""The full and the public spot file: what each holds, what can be published and what the preview serves."""
import dataclasses
import json
import os
import subprocess

import pytest

import aggregate
import preview
import publish
import spot as S
from tests.test_panels import spot_cfg

ALLOWED = ["ATTENTION", "RANDOM"]


def load(path):
    with open(path) as fh:
        return json.load(fh)


def run_spot(tmp_path):
    cfg = spot_cfg(tmp_path)   # the scenario has a done PREFERENCE participant (database id 2)
    res = aggregate.run(cfg)
    return cfg, res, load(os.path.join(cfg.outdir, "spot_users.json")), load(res["spot_full"])


def by_condition(data, condition):
    return [u for u in data["users"] if u["condition"] == condition]


def test_one_run_writes_the_full_and_the_filtered_file(tmp_path):
    cfg, res, public, full = run_spot(tmp_path)
    assert [(u["country"], u["user_id"]) for u in public["users"]] == [(u["country"], u["user_id"]) for u in full["users"]]
    assert full[S.FULL_MARK] and full["as_of"] == res["meta"]["pulled_at"] and S.FULL_MARK not in public
    (hidden,), (shown,) = by_condition(public, "PREFERENCE"), by_condition(full, "PREFERENCE")
    assert hidden["profile_hidden"] and all("u_long" not in e and "rewards" not in e for e in hidden["exchanges"])
    assert all("u_long" in e and "rewards" in e for e in shown["exchanges"]) and "checks" in shown
    assert all("u_long" in e for u in by_condition(public, "ATTENTION") for e in u["exchanges"])
    assert res["files"]["spot_users.json"].endswith("spot_users.json")
    assert all(not p.endswith("spot_users_full.json") for p in res["files"].values())


def test_full_file_is_written_when_publishing_is_off(tmp_path):
    cfg = spot_cfg(tmp_path, "off")
    res = aggregate.run(cfg)
    assert os.path.isfile(res["spot_full"]) and "spot_users.json" not in res["files"]


def test_violations(tmp_path):
    cfg, res, public, full = run_spot(tmp_path)
    assert S.violations(public, ALLOWED) == []
    assert S.violations(full, ALLOWED)                      # the full mark, and the preference fields
    unmarked = {k: v for k, v in full.items() if k != S.FULL_MARK}
    assert len(S.violations(unmarked, ALLOWED)) == 1 and "u_long" in S.violations(unmarked, ALLOWED)[0]
    assert S.violations(unmarked, ["ATTENTION", "PREFERENCE", "RANDOM"]) == []
    # a field nobody listed, and an older file without algorithm types, are refused
    (user,) = by_condition(public, "PREFERENCE")
    user["exchanges"][0]["votes"] = [1]
    assert "votes" in S.violations(public, ALLOWED)[0]
    old = {"users": [{"country": "UK", "user_id": 1, "condition": "PREFERENCE", "exchanges": [{"u_long": [1], "batches": []}]}]}
    assert S.violations(old, ALLOWED) and S.violations([], ALLOWED)


def site_with_remote(cfg, tmp_path):
    for a in (["init", "-q", "-b", "main"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
              ["commit", "-q", "--allow-empty", "-m", "init"], ["remote", "add", "origin", str(tmp_path / "remote.git")]):
        subprocess.run(["git", "-C", cfg.site_dir, *a], check=True)
    subprocess.run(["git", "init", "-q", "--bare", str(tmp_path / "remote.git")], check=True)


def pushed(cfg):
    return publish.git(cfg.site_dir, "ls-tree", "-r", "--name-only", "origin/main").stdout.split()


def test_publish_never_copies_the_full_file_or_a_private_spot_file(tmp_path):
    cfg, res, public, full = run_spot(tmp_path)
    site_with_remote(cfg, tmp_path)
    with pytest.raises(publish.PublishError):
        publish.publish(cfg, {"spot_users_full.json": res["spot_full"]}, res["meta_path"], "t0", warn=lambda m: None)
    warnings = []
    # the full content under the public name is not copied, the other files still go out
    publish.publish(cfg, {**res["files"], "spot_users.json": res["spot_full"]}, res["meta_path"], "t1", warn=warnings.append)
    assert "data/spot_users.json" not in pushed(cfg) and "data/status_bins.csv" in pushed(cfg)
    assert any("NOT published" in w for w in warnings)
    assert not os.path.exists(os.path.join(cfg.site_dir, "data", "spot_users_full.json"))


def test_a_private_public_copy_is_removed_when_the_run_has_no_new_spot_file(tmp_path):
    cfg, res, public, full = run_spot(tmp_path)
    site_with_remote(cfg, tmp_path)
    publish.publish(cfg, res["files"], res["meta_path"], "t1", warn=lambda m: None)
    target = os.path.join(cfg.site_dir, "data", "spot_users.json")
    without = {k: v for k, v in res["files"].items() if k != "spot_users.json"}
    with open(res["meta_path"], "a") as fh:   # a later run always changes meta.json
        fh.write("\n")
    publish.publish(cfg, without, res["meta_path"], "t2", warn=lambda m: None)
    assert "data/spot_users.json" in pushed(cfg)                       # a copy that passes stays
    # as if older code had published every field
    old = {k: v for k, v in full.items() if k != S.FULL_MARK}
    with open(target, "w") as fh:
        json.dump(old, fh)
    publish.git(cfg.site_dir, "commit", "-q", "-m", "old code", "--", "data/spot_users.json")
    warnings = []
    publish.publish(cfg, {**without}, res["meta_path"], "t3", warn=warnings.append)
    assert not os.path.exists(target) and "data/spot_users.json" not in pushed(cfg)
    assert any("is removed" in w for w in warnings)


def test_preview_serves_the_full_file_only_with_full_and_only_locally(tmp_path):
    cfg, res, public, full = run_spot(tmp_path)

    def served(path, spot_file):
        h = preview.Handler.__new__(preview.Handler)
        h.site_dir, h.data_dir, h.spot_file = cfg.site_dir, cfg.outdir, spot_file
        return os.path.basename(h.translate_path(path))

    plain = preview.spot_file_of(False, "0.0.0.0", cfg.outdir)
    assert served("/data/spot_users.json", plain) == "spot_users.json"
    local = preview.spot_file_of(True, "127.0.0.1", cfg.outdir)
    assert served("/data/spot_users.json", local) == "spot_users_full.json"
    for spot_file in (plain, local):
        assert served("/data/spot_users_full.json", spot_file) == "__missing__"
    with pytest.raises(ValueError):
        preview.spot_file_of(True, "0.0.0.0", cfg.outdir)
    with pytest.raises(ValueError):
        preview.spot_file_of(True, "127.0.0.1", str(tmp_path / "empty"))

"""publish.py against a throwaway local bare repo (no network): two machines, one remote."""
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import publish  # noqa: E402
from tests.test_aggregate import make_cfg  # noqa: E402


def sh(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout


def clone(remote, path):
    sh("git", "clone", "-q", str(remote), str(path))
    sh("git", "-C", str(path), "config", "user.email", "test@example.invalid")
    sh("git", "-C", str(path), "config", "user.name", "test")


@pytest.fixture
def two_clones(tmp_path):
    remote = tmp_path / "remote.git"
    sh("git", "init", "-q", "--bare", "-b", "main", str(remote))
    seed = tmp_path / "seed"
    clone(remote, seed)
    (seed / "README.md").write_text("x\n")
    sh("git", "-C", str(seed), "add", "README.md")
    sh("git", "-C", str(seed), "commit", "-q", "-m", "init")
    sh("git", "-C", str(seed), "push", "-q", "origin", "HEAD:main")
    a, b = tmp_path / "a", tmp_path / "b"
    clone(remote, a)
    clone(remote, b)
    return a, b


def out_files(tmp_path, name, text):
    d = tmp_path / ("out_" + name)
    d.mkdir(exist_ok=True)
    (d / "status_bins.csv").write_text(text)
    (d / "meta.json").write_text('{"pulled_at": "%s"}\n' % name)
    return {"status_bins.csv": str(d / "status_bins.csv")}, str(d / "meta.json")


def test_push_then_other_machine_continues(tmp_path, two_clones):
    a, b = two_clones
    cfg_a = make_cfg(tmp_path, site_dir=str(a), machine="barnard")
    cfg_b = make_cfg(tmp_path, site_dir=str(b), machine="laptop")
    publish.publish(cfg_a, *out_files(tmp_path, "t1", "bin_start\n"), "t1", warn=lambda m: None)
    # b has not pulled yet: its push is rejected, and the error says so
    with pytest.raises(publish.PublishError, match="push failed"):
        publish.publish(cfg_b, *out_files(tmp_path, "t2", "bin_start\n1\n"), "t2",
                        warn=lambda m: None)
    # what run.py does first: a fast-forward pull. b's local commit makes it diverge.
    sh("git", "-C", str(b), "reset", "-q", "--hard", "origin/main")
    ok, _ = publish.pull(str(b), "origin", "main")
    assert ok and (b / "data" / "meta.json").read_text() == '{"pulled_at": "t1"}\n'
    warnings = []
    publish.publish(cfg_b, *out_files(tmp_path, "t3", "bin_start\n3\n"), "t3",
                    warn=warnings.append)
    assert warnings and "last data push" in warnings[0]
    log = sh("git", "-C", str(b), "log", "--format=%s", "origin/main")
    assert log.splitlines()[:2] == ["data: pulled_at t3 (laptop)", "data: pulled_at t1 (barnard)"]


def test_commit_touches_only_data_files(tmp_path, two_clones):
    a, _ = two_clones
    (a / "stray.txt").write_text("not for publishing\n")
    sh("git", "-C", str(a), "add", "stray.txt")
    cfg = make_cfg(tmp_path, site_dir=str(a))
    publish.publish(cfg, *out_files(tmp_path, "t1", "bin_start\n"), "t1", warn=lambda m: None)
    files = sh("git", "-C", str(a), "show", "--name-only", "--format=", "HEAD").split()
    assert sorted(files) == ["data/meta.json", "data/status_bins.csv"]

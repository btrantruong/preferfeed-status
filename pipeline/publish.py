"""Git steps: update the clone before a run, and commit + push the data files after it.

The data files are the files of cubes.REGISTRY that the run produced, plus meta.json. Nothing else is ever
copied: participants.csv, history/, detail_cache.json and spot_users.json stay in OUTDIR."""
import os
import shutil
import subprocess
import time

import cubes

DATA_FILES = cubes.FILE_NAMES + ["meta.json"]  # the only names that may be copied into data/


class PublishError(RuntimeError):
    pass


def git(site_dir, *args, check=True):
    return subprocess.run(["git", "-C", site_dir, *args], check=check, capture_output=True,
                          text=True)


def current_branch(site_dir):
    return git(site_dir, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def pull(site_dir, remote, branch):
    """git pull --ff-only. Returns (ok, message)."""
    if current_branch(site_dir) != branch:
        return False, f"clone is not on {branch}"
    r = git(site_dir, "pull", "--ff-only", "--quiet", remote, branch, check=False)
    msg = (r.stderr or r.stdout).strip()
    return r.returncode == 0, msg or "up to date"


def minutes_since_last_data_push(site_dir, remote, branch):
    r = git(site_dir, "log", "-1", "--format=%ct", f"{remote}/{branch}", "--", "data/",
            check=False)
    out = r.stdout.strip()
    if r.returncode != 0 or not out:
        return None
    return (time.time() - int(out)) / 60


def publish(cfg, files, meta_path, pulled_at, warn=print):
    """Copy the data files into the clone, commit only them, push. Returns the commit hash.
    files: {file name: path} of the produced registry files (names outside the registry are refused)."""
    copy = dict(files)
    copy["meta.json"] = meta_path
    outside = [n for n in copy if n not in DATA_FILES]
    if outside:
        raise PublishError(f"not a data file of the registry: {outside}")
    site = cfg.site_dir
    if current_branch(site) != cfg.git_branch:
        raise PublishError(f"clone is not on {cfg.git_branch}; not publishing")
    age = minutes_since_last_data_push(site, cfg.git_remote, cfg.git_branch)
    if age is not None and age < cfg.min_push_gap_min:
        warn(f"warning: last data push was {age:.1f} min ago (MIN_PUSH_GAP_MIN="
             f"{cfg.min_push_gap_min:g}); GitHub Pages allows about 10 builds per hour")
    data_dir = os.path.join(site, "data")
    os.makedirs(data_dir, exist_ok=True)
    for name, src in copy.items():
        shutil.copyfile(src, os.path.join(data_dir, name))
    paths = [f"data/{n}" for n in copy]
    git(site, "add", "--", *paths)
    msg = f"data: pulled_at {pulled_at} ({cfg.machine})"
    r = git(site, "commit", "--quiet", "-m", msg, "--", *paths, check=False)
    if r.returncode != 0:
        raise PublishError(f"git commit failed: {(r.stderr or r.stdout).strip()}")
    r = git(site, "push", "--quiet", cfg.git_remote, f"HEAD:{cfg.git_branch}", check=False)
    if r.returncode != 0:
        raise PublishError("git push failed (the data is still in OUTDIR; python preview.py "
                           f"shows it locally): {(r.stderr or r.stdout).strip()}")
    return git(site, "rev-parse", "--short", "HEAD").stdout.strip()

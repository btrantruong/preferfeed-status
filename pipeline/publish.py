"""Git steps: update the clone before a run, and commit + push the two data files after it."""
import os
import shutil
import subprocess
import time

DATA_FILES = ["status_bins.csv", "meta.json"]


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


def publish(cfg, bins_path, meta_path, pulled_at, warn=print):
    """Copy the data files into the clone, commit only them, push. Returns the commit hash."""
    site = cfg.site_dir
    if current_branch(site) != cfg.git_branch:
        raise PublishError(f"clone is not on {cfg.git_branch}; not publishing")
    age = minutes_since_last_data_push(site, cfg.git_remote, cfg.git_branch)
    if age is not None and age < cfg.min_push_gap_min:
        warn(f"warning: last data push was {age:.1f} min ago (MIN_PUSH_GAP_MIN="
             f"{cfg.min_push_gap_min:g}); GitHub Pages allows about 10 builds per hour")
    data_dir = os.path.join(site, "data")
    os.makedirs(data_dir, exist_ok=True)
    for src, name in zip([bins_path, meta_path], DATA_FILES):
        shutil.copyfile(src, os.path.join(data_dir, name))
    paths = [f"data/{n}" for n in DATA_FILES]
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

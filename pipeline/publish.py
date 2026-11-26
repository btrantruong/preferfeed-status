"""Git steps: update the clone before a run, and commit + push the data files after it.

The data files are the files of cubes.REGISTRY that the run produced, plus meta.json and, when SPOT_PUBLISH is on,
spot_users.json (panel E). Nothing else is ever copied: participants.csv, history/, detail_cache.json and
spot_users_full.json stay in OUTDIR. A spot file that fails spot.violations() is not copied, and a copy already in data/
that fails it is removed."""
import json
import os
import shutil
import subprocess
import time

import cubes
import spot

SPOT_NAME = "spot_users.json"
DATA_FILES = cubes.FILE_NAMES + ["meta.json", "spot_users.json"]  # the only names that may be copied into data/


class PublishError(RuntimeError):
    pass


def git(site_dir, *args, check=True):
    return subprocess.run(["git", "-C", site_dir, *args], check=check, capture_output=True,
                          text=True)


def spot_problems(path, allowed):
    """spot.violations of a file; a file that cannot be read as JSON is a problem too."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        return [f"unreadable ({type(e).__name__})"]
    return spot.violations(data, allowed)


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


def publish(cfg, files, meta_path, pulled_at, warn=print, remove=()):
    """Copy the data files into the clone, commit only them, push. Returns the commit hash.
    files: {file name: path} of the produced files (names outside DATA_FILES are refused).
    remove: names of data files to delete from the clone (a published spot_users.json when SPOT_PUBLISH is off)."""
    copy = dict(files)
    copy["meta.json"] = meta_path
    outside = [n for n in copy if n not in DATA_FILES]
    if outside:
        raise PublishError(f"not a data file of the registry: {outside}")
    if SPOT_NAME in copy:
        problems = spot_problems(copy[SPOT_NAME], cfg.params["spot_profile_conditions"])
        if problems:
            warn(f"warning: {SPOT_NAME} of this run is NOT published, it holds private fields: {'; '.join(problems[:3])}"
                 f" ({len(problems)} problems)")
            del copy[SPOT_NAME]
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
    for name in remove:
        if name not in DATA_FILES or name == "meta.json":
            raise PublishError(f"cannot remove {name}")
        target = os.path.join(data_dir, name)
        if os.path.isfile(target):
            os.remove(target)
            paths.append(f"data/{name}")   # the deletion is staged by git add and committed with the rest
    # a public copy that this run does not replace is checked too (a failed spot build, or older code elsewhere)
    published = os.path.join(data_dir, SPOT_NAME)
    if SPOT_NAME not in copy and os.path.isfile(published):
        problems = spot_problems(published, cfg.params["spot_profile_conditions"])
        if problems:
            warn(f"warning: the published {SPOT_NAME} holds private fields and is removed: {'; '.join(problems[:3])}"
                 f" ({len(problems)} problems)")
            tracked = git(site, "ls-files", "--", f"data/{SPOT_NAME}").stdout.strip()
            os.remove(published)
            if tracked:
                paths.append(f"data/{SPOT_NAME}")
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

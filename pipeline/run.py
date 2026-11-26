"""One status pull: load config, lock, git pull, aggregate, print a summary, publish.

Usage (through run.sh, which picks the uv env):
  ./run.sh                     pull, aggregate and push
  ./run.sh --no-push           pull and aggregate only; look at the summary first
  ./run.sh --countries UK,DE   query only these countries (the others keep their last published data)
  ./run.sh --set LAUNCH=2026-11-20T14:00 --no-push   override a config value for this run
"""
import argparse
import fcntl
import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import aggregate  # noqa: E402
import config as cfgmod  # noqa: E402
import publish  # noqa: E402


@contextmanager
def lock(path):
    fh = open(path, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        sys.exit(f"another run holds {path}; wait for it to finish")
    try:
        yield
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


def log_line(outdir, record):
    with open(os.path.join(outdir, "run.log"), "a") as fh:
        fh.write(json.dumps(record) + "\n")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--no-push", action="store_true", help="do not commit or push")
    p.add_argument("--no-pull", action="store_true", help="skip git pull before the run")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                   help="override a config value for this run (repeatable)")
    p.add_argument("--countries", metavar="CC,CC", help="query only these countries; same as --set PULL_COUNTRIES=CC,CC")
    args = p.parse_args(argv)
    if args.countries:
        args.set = args.set + [f"PULL_COUNTRIES={args.countries}"]

    cfg = cfgmod.load(HERE, args.set)
    os.makedirs(cfg.outdir, exist_ok=True)
    started = datetime.now(timezone.utc)
    record = {"started": started.strftime("%Y-%m-%dT%H:%M:%SZ"), "machine": cfg.machine,
              "launch": cfg.launch, "overrides": args.set, "pushed": False}
    with lock(os.path.join(cfg.outdir, "run.lock")):
        if not args.no_pull:
            ok, msg = publish.pull(cfg.site_dir, cfg.git_remote, cfg.git_branch)
            record["git_pull"] = "ok" if ok else f"failed: {msg}"
            if not ok:
                print(f"warning: git pull failed ({msg}); continuing with the local clone")
        try:
            result = aggregate.run(cfg)
        except aggregate.NoDataError as e:
            record["error"] = str(e)
            log_line(cfg.outdir, record)
            sys.exit(f"error: {e}; nothing written or published")

        meta = result["meta"]
        record.update({"pulled_at": meta["pulled_at"],
                       "n": {c: v["n"] for c, v in meta["countries"].items()},
                       "failed": result["failures"]})
        print(f"pulled_at {meta['pulled_at']} on {cfg.machine}, launch {meta['launch']}")
        print(aggregate.summary_table(result).to_string(index=False))
        for cc, err in result["failures"].items():
            as_of = meta["countries"][cc]["as_of"]
            print(f"failed {cc}: {err} (page keeps data as of {as_of})")
        print(f"detail ({cfg.params['detail']}): " + ", ".join(f"{c} {s}" for c, s in result["detail_status"].items()))
        for cc, err in result["detail_errors"].items():
            print(f"detail failed {cc}: {err} (detail files keep that country's last published rows)")
        print(f"ids report (local only): {result['ids_report']}")
        print(f"spot check (panel D, {'published' if cfg.params['spot_publish'] == 'on' else 'not published'}): {result['spot']}")
        big = [f"{n} {sz // 1024} KB" for n, sz in result["sizes"].items() if sz > cfg.params["max_file_kb"] * 1024]
        print("file sizes: " + ", ".join(f"{n} {sz / 1024:.0f} KB" for n, sz in result["sizes"].items()))
        if big:
            print(f"warning: larger than MAX_FILE_KB={cfg.params['max_file_kb']}: {', '.join(big)}")
        print(f"files: {cfg.outdir}")

        if args.no_push:
            print("--no-push: not published")
        else:
            try:
                commit = publish.publish(cfg, result["files"], result["meta_path"], meta["pulled_at"], remove=result["remove"])
                record["pushed"], record["commit"] = True, commit
                print(f"published commit {commit}")
            except publish.PublishError as e:
                record["error"] = str(e)
                log_line(cfg.outdir, record)
                sys.exit(f"error: {e}")
        log_line(cfg.outdir, record)


if __name__ == "__main__":
    main()

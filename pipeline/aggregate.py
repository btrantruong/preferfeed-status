"""Pull, classify and bin: writes status_bins.csv, meta.json, participants.csv and the history.

status_bins.csv (published): bin_start (UTC ISO), country, status, reason, n; only non-zero rows.
Bins are BIN_MINUTES wide and start at LAUNCH. A country that fails keeps its bins from the
last published data/status_bins.csv (same launch and bin width), and meta.json keeps its as_of.
"""
import json
import os
import subprocess
from datetime import datetime, timezone

import pandas as pd

import classify as C
import db

BIN_COLUMNS = ["bin_start", "country", "status", "reason", "n"]
HISTORY_COLUMNS = ["pulled_at", "machine", "launch_utc"] + BIN_COLUMNS


class NoDataError(RuntimeError):
    """No server returned data; nothing should be published."""


def iso_utc(ms):
    return pd.Timestamp(int(ms), unit="ms", tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def launch_ms(launch, tz):
    ts = pd.Timestamp(launch)
    ts = ts.tz_localize(tz) if ts.tzinfo is None else ts
    return ts.value // 1_000_000


def git_short_hash(repo):
    try:
        return subprocess.run(["git", "-C", repo, "rev-parse", "--short", "HEAD"], check=True,
                              capture_output=True, text=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(text)
    os.replace(tmp, path)


def pull(cfg, pulled_ms, reader_cls=None):
    """Return (visited, errors_long, status {cc: 'ok'|'failed'}, errors {cc: message})."""
    if reader_cls is None:
        reader_cls, _ = db.import_reader(cfg.pfda_dir)
    reader, failures = db.make_reader(reader_cls, cfg.creds, cfg.creds_keys, cfg.countries,
                                      cfg.connect_timeout_s)
    start = cfg.launch
    end = iso_utc(pulled_ms + 24 * 3600 * 1000)  # open-ended in practice; tolerates clock skew
    frames, errs = [], []
    for cc in cfg.countries:
        if cc in failures:
            continue
        try:
            v = db.read_visited(reader, cc, start, end, cfg.tz)
        except Exception as e:  # one server down must not stop the others
            failures[cc] = f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"
            continue
        frames.append(v)
        errs.append(C.explode_errors(v, cc))
    status = {cc: ("failed" if cc in failures else "ok") for cc in cfg.countries}
    visited = (pd.concat(frames, ignore_index=True) if frames
               else pd.DataFrame(columns=db.COLUMNS + ["country"]))
    errors_long = (pd.concat(errs, ignore_index=True) if errs
                   else pd.DataFrame(columns=C.ERROR_COLUMNS))
    return visited, errors_long, status, failures


def bin_counts(participants, launch_at_ms, bin_minutes):
    if participants.empty:
        return pd.DataFrame(columns=BIN_COLUMNS)
    bin_ms = bin_minutes * 60_000
    start = launch_at_ms + ((participants["created_at"] - launch_at_ms) // bin_ms) * bin_ms
    counts = (participants.assign(bin_ms=start)
              .groupby(["bin_ms", "country", "status", "reason"]).size().rename("n")
              .reset_index())
    counts["bin_start"] = counts["bin_ms"].map(iso_utc)
    return counts[BIN_COLUMNS].sort_values(["bin_start", "country", "status", "reason"])


def previous_published(site_dir):
    """(bins DataFrame, meta dict) from the clone's data/, or (None, None)."""
    bins_path = os.path.join(site_dir, "data", "status_bins.csv")
    meta_path = os.path.join(site_dir, "data", "meta.json")
    if not (os.path.isfile(bins_path) and os.path.isfile(meta_path)):
        return None, None
    with open(meta_path) as fh:
        meta = json.load(fh)
    return pd.read_csv(bins_path, dtype={"n": "int64"}, keep_default_na=False), meta


def carry_over(bins, status, prev_bins, prev_meta, cfg, launch_iso):
    """For failed countries, take bins and as_of from the previous published run if it used
    the same launch and bin width. Returns (bins, {cc: as_of or None})."""
    same = (prev_meta is not None and prev_meta.get("launch_utc") == launch_iso
            and prev_meta.get("bin_minutes") == cfg.bin_minutes)
    as_of = {}
    keep = [bins]
    for cc, st in status.items():
        if st == "ok":
            continue
        prev_c = (prev_meta or {}).get("countries", {}).get(cc, {})
        if same and prev_c.get("as_of"):
            keep.append(prev_bins[prev_bins["country"] == cc][BIN_COLUMNS])
            as_of[cc] = prev_c["as_of"]
        else:
            as_of[cc] = None
    out = pd.concat([k for k in keep if not k.empty], ignore_index=True) if any(
        not k.empty for k in keep) else pd.DataFrame(columns=BIN_COLUMNS)
    return out.sort_values(["bin_start", "country", "status", "reason"]), as_of


def build_meta(cfg, pulled_ms, launch_at_ms, status, failures, as_of_failed, participants):
    pulled_iso = iso_utc(pulled_ms)
    n_by_c = participants.groupby("country").size().to_dict() if not participants.empty else {}
    countries = {}
    for cc in cfg.countries:
        ok = status[cc] == "ok"
        countries[cc] = {"status": status[cc],
                         "as_of": pulled_iso if ok else as_of_failed.get(cc),
                         "n": int(n_by_c.get(cc, 0)) if ok else None}
    return {
        "pulled_at": pulled_iso,
        "launch": pd.Timestamp(launch_at_ms, unit="ms", tz="UTC").tz_convert(cfg.tz).isoformat(),
        "launch_utc": iso_utc(launch_at_ms),
        "tz": cfg.tz,
        "bin_minutes": cfg.bin_minutes,
        "session_min": cfg.session_min,
        "ignore_codes": cfg.ignore_codes,
        "stop_codes": cfg.stop_codes,
        "idle_min_seconds": cfg.idle_min_seconds,
        "idle_min_posts": cfg.idle_min_posts,
        "stale_after_min": cfg.stale_after_min,
        "refresh_min": cfg.refresh_min,
        "scripts_url": cfg.scripts_url,
        "code_version": git_short_hash(cfg.site_dir),
        "categories": [{"status": s, "reason": r} for s, r in C.categories(cfg.stop_codes)],
        "countries": countries,
    }


def append_history(outdir, bins, pulled_iso, machine, launch_iso):
    path = os.path.join(outdir, "history", "status_bins_history.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rows = bins.assign(pulled_at=pulled_iso, machine=machine, launch_utc=launch_iso)[HISTORY_COLUMNS]
    rows.to_csv(path, mode="a", header=not os.path.isfile(path), index=False)


def run(cfg, pulled_ms=None, reader_cls=None):
    """One aggregation. Writes to cfg.outdir; returns a dict for the summary and the publish step."""
    if pulled_ms is None:
        pulled_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    launch_at_ms = launch_ms(cfg.launch, cfg.tz)
    visited, errors_long, status, failures = pull(cfg, pulled_ms, reader_cls)
    if all(s == "failed" for s in status.values()):
        raise NoDataError(f"no server returned data: {failures}")

    participants = C.classify(visited, errors_long, pulled_ms, cfg.session_min,
                              cfg.ignore_codes, cfg.stop_codes)
    bins = bin_counts(participants, launch_at_ms, cfg.bin_minutes)
    prev_bins, prev_meta = previous_published(cfg.site_dir)
    bins, as_of_failed = carry_over(bins, status, prev_bins, prev_meta, cfg,
                                    iso_utc(launch_at_ms))
    meta = build_meta(cfg, pulled_ms, launch_at_ms, status, failures, as_of_failed, participants)

    os.makedirs(cfg.outdir, exist_ok=True)
    bins_path = os.path.join(cfg.outdir, "status_bins.csv")
    meta_path = os.path.join(cfg.outdir, "meta.json")
    write_atomic(bins_path, bins.to_csv(index=False))
    write_atomic(meta_path, json.dumps(meta, indent=1) + "\n")
    write_atomic(os.path.join(cfg.outdir, "participants.csv"), participants.to_csv(index=False))
    append_history(cfg.outdir, bins, meta["pulled_at"], cfg.machine, meta["launch_utc"])
    return {"meta": meta, "bins_path": bins_path, "meta_path": meta_path,
            "participants": participants, "failures": failures}


def summary_table(result):
    """Per-country n, done, cancelled, incomplete for this pull (failed servers marked)."""
    p = result["participants"]
    meta = result["meta"]
    rows = []
    for cc, info in meta["countries"].items():
        sub = p[p["country"] == cc] if not p.empty else p
        row = {"country": cc, "status": info["status"], "n": len(sub)}
        for s in C.STATUSES:
            row[s] = int((sub["status"] == s).sum()) if not sub.empty else 0
        if info["status"] == "failed":
            row.update({"n": None, **{s: None for s in C.STATUSES}})
        rows.append(row)
    df = pd.DataFrame(rows)
    ok = df[df["status"] == "ok"]
    total = {"country": "ALL(ok)", "status": "", "n": int(ok["n"].sum())}
    total.update({s: int(ok[s].sum()) for s in C.STATUSES})
    return pd.concat([df, pd.DataFrame([total])], ignore_index=True)

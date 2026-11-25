"""Pull, classify, bin and build every published file; write them with meta.json to OUTDIR.

Files are listed in cubes.REGISTRY (columns, window kind, builder). bin_start is UTC ISO 8601; participant
files use BIN_MINUTES bins from LAUNCH, event files use EVENT_BIN_MINUTES bins. Only non-zero rows are listed.

Failure handling. A country whose core pull fails keeps its rows from the last published files (same launch
and bin widths), and meta.json keeps its as_of. The detail files (record_entry, algo_exchange) are a separate
failure domain: a country whose detail pull fails, or all countries when DETAIL=off, keep their last published
detail rows, marked with their own as_of in meta.files and meta.detail.

Row-level files stay in OUTDIR: participants.csv, history/, detail_cache.json and spot_users.json.
"""
import json
import os
import subprocess
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import checks
import classify as C
import cubes
import db
import detail as D
import spot as S

PREV_COUNTRY_FILE = "status_bins.csv"  # the only published file of the first page version
BIN_COLUMNS = cubes.BY_NAME["status_bins.csv"].columns
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


# ---- core pull ---------------------------------------------------------------------------------------
def make_source(cfg, reader_cls=None):
    """(source, failures {country: error}) for the live databases or the export folder of SOURCE."""
    if cfg.source != "live":
        return db.ExportSource(cfg.source[len("export:"):]), {}
    if reader_cls is None:
        reader_cls, _ = db.import_reader(cfg.pfda_dir)
    reader, failures = db.make_reader(reader_cls, cfg.creds, cfg.creds_keys, cfg.countries, cfg.connect_timeout_s)
    return db.LiveSource(reader, cfg.params["detail_timeout_s"]), failures


def pull(cfg, source, failures, pulled_ms):
    """Return (visited, errors_long, status {cc: 'ok'|'failed'}, failures {cc: message})."""
    end = iso_utc(pulled_ms + 24 * 3600 * 1000)  # open-ended in practice; tolerates clock skew
    frames, errs = [], []
    for cc in cfg.countries:
        if cc in failures:
            continue
        try:
            v = source.core(cc, cfg.launch, end, cfg.tz)
        except Exception as e:  # one server down must not stop the others
            failures[cc] = f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"
            continue
        frames.append(v)
        errs.append(C.explode_errors(v, cc))
    status = {cc: ("failed" if cc in failures else "ok") for cc in cfg.countries}
    visited = (pd.concat(frames, ignore_index=True) if frames
               else pd.DataFrame(columns=db.COLUMNS + ["country"]))
    errors_long = (pd.concat(errs, ignore_index=True) if errs else pd.DataFrame(columns=C.ERROR_COLUMNS))
    errors_long["ts"] = pd.to_numeric(errors_long["timestamp_server"], errors="coerce")
    return visited, errors_long, status, failures


def participants_frame(visited, errors_long, classified, cfg, launch_at_ms):
    """One row per participant: status and reason, the visited_users columns the charts need, the bin."""
    if classified.empty:
        cols = list(classified.columns) + ["condition", "started", "viewed_posts", "attempt", "created_bin",
                                           "has_server_error", "starts", "after_stop"]
        return pd.DataFrame(columns=cols)
    extra = visited[["country", "id", "condition", "started", "viewed_posts", "attempt"]].rename(
        columns={"id": "user_id"})
    P = classified.merge(extra, on=["country", "user_id"], how="left")
    bin_ms = cfg.bin_minutes * 60_000
    P["created_bin"] = launch_at_ms + ((P["created_at"] - launch_at_ms) // bin_ms) * bin_ms
    srv = errors_long[errors_long["code"] == cfg.params["server_error_code"]]
    keys = set(zip(srv["country"], srv["user_id"]))
    P["has_server_error"] = [k in keys for k in zip(P["country"], P["user_id"])]
    P["starts"] = np.nan
    P["after_stop"] = False
    return P


def apply_attempts(P, errors_long, cfg, detail_results):
    """starts (timeline starts) and after_stop (retook after a stop) per participant. The attempt column of
    visited_users gives starts without a detail pull; init rows give them where the detail pull ran."""
    stop = list(cfg.stop_codes.values())
    for cc in cfg.countries:
        m = P["country"] == cc
        if not m.any():
            continue
        sub = P[m]
        vis = {(cc, u): a for u, a in zip(sub["user_id"], sub["attempt"]) if a is not None and not pd.isna(a)}
        res = detail_results.get(cc)
        starts = res["starts"] if res else checks.starts_per_participant(sub, None, vis)
        P.loc[m, "starts"] = starts.reindex(sub.index)
        final_start = res["final_start"] if res else {}
        known = P.index[m & P["starts"].notna()]
        if len(known):
            P.loc[known, "after_stop"] = checks.retook_after_stop(
                P.loc[known], P.loc[known, "starts"], errors_long[errors_long["country"] == cc], stop, final_start)
    return P


def apply_flags(P, detail_results):
    """Flags, requests and n_records of done participants in the countries whose detail pull ran."""
    for c in checks.ALL_FLAGS:
        P[c] = False
    P["requests"], P["n_records"] = np.nan, np.nan
    for cc, res in detail_results.items():
        ex = res["ex"]
        fin = ex[ex["attempt_id"] == ex["final_attempt"]] if not ex.empty else ex
        by_key = {k: g for k, g in fin.groupby(["country", "user_id"])} if not fin.empty else {}
        m = (P["country"] == cc) & (P["status"] == "done")
        done = P[m]
        if done.empty:
            continue
        ft = checks.flags_table(done, by_key, res["counts"]).set_index(["country", "user_id"])
        idx = list(zip(done["country"], done["user_id"]))
        for c in checks.ALL_FLAGS + ["requests", "n_records"]:
            P.loc[m, c] = ft.loc[idx, c].to_numpy()
    return P


# ---- assembling files --------------------------------------------------------------------------------
def previous_published(site_dir):
    """(prev_meta, {name: DataFrame as text}) from the clone's data/, or (None, {})."""
    meta_path = os.path.join(site_dir, "data", "meta.json")
    if not os.path.isfile(meta_path):
        return None, {}
    with open(meta_path) as fh:
        meta = json.load(fh)
    frames = {}
    for name in cubes.FILE_NAMES:
        path = os.path.join(site_dir, "data", name)
        if os.path.isfile(path):
            frames[name] = pd.read_csv(path, dtype=str, keep_default_na=False)
    return meta, frames


def prev_as_of(prev_meta, name, cc):
    f = (prev_meta.get("files") or {}).get(name)
    if f is not None:
        return (f.get("as_of") or {}).get(cc)
    if name == PREV_COUNTRY_FILE:  # published before meta.files existed
        return (prev_meta.get("countries", {}).get(cc) or {}).get("as_of")
    return None


def same_basis(prev_meta, cfg, launch_iso):
    return (prev_meta is not None and prev_meta.get("launch_utc") == launch_iso
            and prev_meta.get("bin_minutes") == cfg.bin_minutes
            and prev_meta.get("event_bin_minutes", cfg.params["event_bin_minutes"]) == cfg.params["event_bin_minutes"])


def fresh_countries(spec, core_ok, attempt_ok, detail_status, mode):
    if spec.coverage == "core":
        return set(core_ok)
    if spec.coverage == "attempts":
        return set(core_ok) & (set(attempt_ok) | {c for c, s in detail_status.items() if s == "ok"})
    ok = {c for c, s in detail_status.items() if s == "ok"} & set(core_ok)
    return ok if (spec.coverage == "detail" or mode == "full") else set()


def assemble(cfg, inputs, core_ok, attempt_ok, detail_status, prev_meta, prev_frames, launch_iso, pulled_iso):
    """Build every file, add the rows carried over for countries without fresh data.
    Returns ({name: frame}, {name: {"window", "columns", "as_of"}}) for the files to write."""
    mode = cfg.params["detail"]
    same = same_basis(prev_meta, cfg, launch_iso)
    out, info = {}, {}
    for spec in cubes.REGISTRY:
        fresh = fresh_countries(spec, core_ok, attempt_ok, detail_status, mode)
        frame = spec.build(inputs)
        frame = frame[frame["country"].isin(fresh)] if not frame.empty else frame
        parts, as_of = [frame.astype(str)] if not frame.empty else [], {cc: pulled_iso for cc in fresh}
        for cc in cfg.countries:
            if cc in fresh or not same:
                continue
            when = prev_as_of(prev_meta, spec.name, cc)
            prev = prev_frames.get(spec.name)
            if when and prev is not None:
                as_of[cc] = when
                rows = prev[prev["country"] == cc]
                if not rows.empty:
                    parts.append(rows[spec.columns])
        if not as_of:
            continue  # nothing fresh and nothing to carry: the file is not published
        merged = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=spec.columns)
        key = [c for c in spec.columns if c != "n"][:len(spec.columns) - 1]
        out[spec.name] = merged[spec.columns].sort_values(key, kind="stable").reset_index(drop=True)
        info[spec.name] = {"window": spec.window, "columns": spec.columns, "as_of": as_of}
    return out, info


def build_meta(cfg, pulled_ms, launch_at_ms, status, detail_status, detail_prev, files_info, participants):
    pulled_iso = iso_utc(pulled_ms)
    n_by_c = participants.groupby("country").size().to_dict() if not participants.empty else {}
    countries = {}
    for cc in cfg.countries:
        ok = status[cc] == "ok"
        countries[cc] = {"status": status[cc], "as_of": pulled_iso if ok else files_info.get(
            cubes.REGISTRY[0].name, {}).get("as_of", {}).get(cc),
            "n": int(n_by_c.get(cc, 0)) if ok else None}
    detail = {cc: {"status": detail_status.get(cc, "off"),
                   "as_of": pulled_iso if detail_status.get(cc) == "ok" else detail_prev.get(cc)}
              for cc in cfg.countries}
    return {
        "pulled_at": pulled_iso,
        "launch": pd.Timestamp(launch_at_ms, unit="ms", tz="UTC").tz_convert(cfg.tz).isoformat(),
        "launch_utc": iso_utc(launch_at_ms),
        "tz": cfg.tz,
        "bin_minutes": cfg.bin_minutes,
        "event_bin_minutes": cfg.params["event_bin_minutes"],
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
        "detail_mode": cfg.params["detail"],
        "detail": detail,
        "params": {k.lower(): cfg.params[k.lower()] for k in __import__("config").PAGE_PARAMS},
        "flow_nodes": cubes.FLOW_NODES,
        "files": files_info,
    }


def append_history(outdir, bins, pulled_iso, machine, launch_iso):
    path = os.path.join(outdir, "history", "status_bins_history.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rows = bins.assign(pulled_at=pulled_iso, machine=machine, launch_utc=launch_iso)[HISTORY_COLUMNS]
    rows.to_csv(path, mode="a", header=not os.path.isfile(path), index=False)


# ---- spot check (local only) -------------------------------------------------------------------------
def write_spot(cfg, source, P, ex_all, detail_status, outdir):
    """OUTDIR/spot_users.json for the listed participants, or a note why it was not written. Never published."""
    path = os.path.join(outdir, "spot_users.json")
    if cfg.params["detail"] == "off":
        return "off"
    if not cfg.inventory_file or not os.path.isfile(cfg.inventory_file):
        return "no INVENTORY_FILE"
    picks, rows, info = {}, {}, {}
    try:
        for cc in cfg.countries:
            if detail_status.get(cc) != "ok":
                continue
            ids, defaults = S.select_users(P, ex_all, cfg.params, cc)
            if not ids:
                continue
            e = ex_all[(ex_all["country"] == cc) & (ex_all["attempt_id"] == ex_all["final_attempt"])]
            n_nb = e[e["endpoint"] == "next_batch"].groupby("user_id").size()
            sub = P[(P["country"] == cc) & P["user_id"].isin(ids)][["user_id", "condition", "created_at"]].copy()
            sub["n_next_batch"] = sub["user_id"].map(n_nb).fillna(0).astype(int)
            picks[cc] = (ids, defaults, sub)
            rows[cc] = source.spot(cc, ids)
        if not picks:
            write_atomic(path, json.dumps({"users": [], "posts": {}, "inventory": {}, "dims": S.PROFILE_DIMS}))
            return "no participants"
        inv_all = pd.read_parquet(cfg.inventory_file, columns=["post_id", "country", "platform", "text"]
                                  + S.PROFILE_DIMS).drop_duplicates("post_id").set_index("post_id")
        inv = {cc: inv_all[inv_all["country"] == cc] for cc in picks}
        data = S.build_spot(picks, rows, inv, cfg.params, S.file_sha256(cfg.inventory_file))
        write_atomic(path, json.dumps(data, allow_nan=False))
        return f"{len(data['users'])} participants"
    except Exception as e:  # the spot check must never fail a pull
        return f"failed: {type(e).__name__}"


# ---- one run -----------------------------------------------------------------------------------------
def run(cfg, pulled_ms=None, reader_cls=None):
    """One aggregation. Writes to cfg.outdir; returns a dict for the summary and the publish step."""
    if pulled_ms is None:
        pulled_ms = (int(pd.Timestamp(cfg.pulled_at).value // 1_000_000) if cfg.pulled_at
                     else int(datetime.now(timezone.utc).timestamp() * 1000))
    launch_at_ms = launch_ms(cfg.launch, cfg.tz)
    launch_iso = iso_utc(launch_at_ms)
    source, failures = make_source(cfg, reader_cls)
    visited, errors_long, status, failures = pull(cfg, source, failures, pulled_ms)
    if all(s == "failed" for s in status.values()):
        raise NoDataError(f"no server returned data: {failures}")
    core_ok = [cc for cc, s in status.items() if s == "ok"]

    classified = C.classify(visited, errors_long, pulled_ms, cfg.session_min, cfg.ignore_codes, cfg.stop_codes)
    P = participants_frame(visited, errors_long, classified, cfg, launch_at_ms)

    os.makedirs(cfg.outdir, exist_ok=True)
    cache = D.load_cache(cfg.outdir)
    end_ms = pulled_ms + 24 * 3600 * 1000
    results, detail_status, detail_errors = D.run(cfg, source, P, launch_at_ms, end_ms, pulled_ms, core_ok, cache)
    if results:
        D.save_cache(cfg.outdir, cache)
    P = apply_attempts(P, errors_long, cfg, results)
    P = apply_flags(P, results)
    ex_all = pd.concat([r["ex"] for r in results.values()], ignore_index=True) if results else None
    act = pd.concat([r["active"] for r in results.values() if r["active"] is not None], ignore_index=True) \
        if any(r["active"] is not None for r in results.values()) else None
    inputs = cubes.Inputs(P=P, events=errors_long, ex=ex_all, active=act, launch_ms=launch_at_ms,
                          p=cfg.params, bin_minutes=cfg.bin_minutes)

    attempt_ok = [cc for cc in core_ok if P[P["country"] == cc].empty or P.loc[P["country"] == cc, "attempt"].notna().any()]
    prev_meta, prev_frames = previous_published(cfg.site_dir)
    frames, files_info = assemble(cfg, inputs, core_ok, attempt_ok, detail_status, prev_meta, prev_frames,
                                  launch_iso, iso_utc(pulled_ms))
    detail_prev = {cc: ((prev_meta or {}).get("detail", {}).get(cc) or {}).get("as_of") for cc in cfg.countries} \
        if same_basis(prev_meta, cfg, launch_iso) else {}
    meta = build_meta(cfg, pulled_ms, launch_at_ms, status, detail_status, detail_prev, files_info, classified)

    paths, sizes = {}, {}
    for name, frame in frames.items():
        paths[name] = os.path.join(cfg.outdir, name)
        write_atomic(paths[name], frame.to_csv(index=False))
        sizes[name] = os.path.getsize(paths[name])
    meta_path = os.path.join(cfg.outdir, "meta.json")
    write_atomic(meta_path, json.dumps(meta, indent=1) + "\n")
    write_atomic(os.path.join(cfg.outdir, "participants.csv"), P.drop(columns=["attempt"]).to_csv(index=False))
    spot_note = write_spot(cfg, source, P, ex_all, detail_status, cfg.outdir)
    if PREV_COUNTRY_FILE in frames:
        append_history(cfg.outdir, frames[PREV_COUNTRY_FILE], meta["pulled_at"], cfg.machine, meta["launch_utc"])
    return {"meta": meta, "meta_path": meta_path, "files": paths, "bins_path": paths.get(PREV_COUNTRY_FILE),
            "participants": classified, "failures": failures, "detail_status": detail_status,
            "detail_errors": detail_errors, "sizes": sizes, "spot": spot_note}


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

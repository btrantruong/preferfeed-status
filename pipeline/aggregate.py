"""Pull, classify, bin and build every published file; write them with meta.json to OUTDIR.

Files are listed in cubes.REGISTRY (columns, window kind, builder). bin_start is UTC ISO 8601; participant
files use BIN_MINUTES bins from LAUNCH, event files use EVENT_BIN_MINUTES bins. Only non-zero rows are listed.

Failure handling. A country whose core pull fails keeps its rows from the last published files (same launch
and bin widths), and meta.json keeps its as_of. The detail files (record_entry, algo_exchange) are a separate
failure domain: a country whose detail pull fails, or all countries when DETAIL=off, keep their last published
detail rows, marked with their own as_of in meta.files and meta.detail.

Row-level files stay in OUTDIR: participants.csv, history/, detail_cache.json and spot_users_full.json. spot_users.json
(panel E, the filtered copy) is published with the data when SPOT_PUBLISH is on.
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
import outcomes as O
import db
import detail as D
import report as R
import sessions as SS
import spot as S
import trajectory as TR

SPOT_FILE = "spot_users.json"
SPOT_FULL_FILE = "spot_users_full.json"   # OUTDIR only, never published
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
    reader, failures = db.make_reader(reader_cls, cfg.creds, cfg.creds_keys, cfg.pulled_countries(), cfg.connect_timeout_s)
    return db.LiveSource(reader, cfg.params["detail_timeout_s"]), failures


def pull(cfg, source, failures, pulled_ms):
    """Return (visited, errors_long, status {cc: 'ok'|'failed'|'not_pulled'}, failures {cc: message}).
    Only the countries of cfg.pulled_countries() are queried, each from its own launch time."""
    end = iso_utc(pulled_ms + 24 * 3600 * 1000)  # open-ended in practice; tolerates clock skew
    frames, errs = [], []
    for cc in cfg.pulled_countries():
        if cc in failures:
            continue
        try:
            v = source.core(cc, cfg.launch_of(cc), end, cfg.tz)
        except Exception as e:  # one server down must not stop the others
            failures[cc] = f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"
            continue
        frames.append(v)
        errs.append(C.explode_errors(v, cc))
    pulled = cfg.pulled_countries()
    status = {cc: ("not_pulled" if cc not in pulled else "failed" if cc in failures else "ok") for cc in cfg.countries}
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


def same_basis(prev_meta, cfg, launch_iso, cc=None, cc_launch_iso=None):
    """Published data can be carried over: same bin origin and widths and, for one country, the same launch time
    of that country (a meta without a per-country launch is read as the shared launch)."""
    ok = (prev_meta is not None and prev_meta.get("launch_utc") == launch_iso
          and prev_meta.get("bin_minutes") == cfg.bin_minutes
          and prev_meta.get("event_bin_minutes", cfg.params["event_bin_minutes"]) == cfg.params["event_bin_minutes"])
    if ok and cc is not None:
        ok = ((prev_meta.get("countries", {}).get(cc) or {}).get("launch_utc", launch_iso)
              == (cc_launch_iso or launch_iso))
    return ok


def fresh_countries(spec, core_ok, detail_status, mode):
    if spec.coverage == "core":
        return set(core_ok)
    ok = {c for c, s in detail_status.items() if s == "ok"} & set(core_ok)
    return ok if (spec.coverage == "detail" or mode == "full") else set()


def assemble(cfg, inputs, core_ok, detail_status, prev_meta, prev_frames, launch_iso, pulled_iso,
             launch_cc_iso=None):
    """Build every file, add the rows carried over for countries without fresh data.
    Returns ({name: frame}, {name: {"window", "columns", "as_of"}}) for the files to write."""
    mode = cfg.params["detail"]
    launch_cc_iso = launch_cc_iso or {}
    out, info = {}, {}
    for spec in cubes.REGISTRY:
        fresh = fresh_countries(spec, core_ok, detail_status, mode)
        frame = spec.build(inputs)
        frame = frame[frame["country"].isin(fresh)] if not frame.empty else frame
        parts, as_of = [frame.astype(str)] if not frame.empty else [], {cc: pulled_iso for cc in fresh}
        for cc in cfg.countries:
            if cc in fresh or not same_basis(prev_meta, cfg, launch_iso, cc, launch_cc_iso.get(cc)):
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


def build_meta(cfg, pulled_ms, launch_at_ms, status, detail_status, detail_prev, files_info, participants,
               launch_cc_iso=None, spot=None, sessions=None):
    pulled_iso = iso_utc(pulled_ms)
    n_by_c = participants.groupby("country").size().to_dict() if not participants.empty else {}
    countries = {}
    for cc in cfg.countries:
        ok = status[cc] == "ok"
        countries[cc] = {"status": status[cc], "as_of": pulled_iso if ok else files_info.get(
            cubes.REGISTRY[0].name, {}).get("as_of", {}).get(cc),
            "n": int(n_by_c.get(cc, 0)) if ok else None,
            "launch_utc": (launch_cc_iso or {}).get(cc) or iso_utc(launch_at_ms)}
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
        "sessions": sessions,   # T_ref and its source for the in session / left rule, or None
        "spot": spot,   # panel E: {"as_of", "n_users"} of the published spot_users.json, or None
    }


def append_history(outdir, bins, pulled_iso, machine, launch_iso):
    path = os.path.join(outdir, "history", "status_bins_history.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rows = bins.assign(pulled_at=pulled_iso, machine=machine, launch_utc=launch_iso)[HISTORY_COLUMNS]
    rows.to_csv(path, mode="a", header=not os.path.isfile(path), index=False)


# ---- spot check (panel E) ----------------------------------------------------------------------------
def write_spot_files(data, allowed, as_of, outdir):
    """The full file (local) and the public one derived from it."""
    full = {**data, S.FULL_MARK: True, "as_of": as_of}
    write_atomic(os.path.join(outdir, SPOT_FULL_FILE), json.dumps(full, allow_nan=False))
    write_atomic(os.path.join(outdir, SPOT_FILE), json.dumps(S.public_view(data, allowed), allow_nan=False))


def write_spot(cfg, source, P, ex_all, detail_status, outdir, as_of):
    """OUTDIR/spot_users_full.json and spot_users.json for the listed participants. Returns (note, n_users): n_users
    is 0 when nothing was written or the list is empty. Only spot_users.json is published, and only if SPOT_PUBLISH
    is on (publish.py)."""
    allowed = cfg.params["spot_profile_conditions"]
    if cfg.params["detail"] == "off":
        return "off", 0
    if not cfg.inventory_file or not os.path.isfile(cfg.inventory_file):
        return "no INVENTORY_FILE", 0
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
            write_spot_files({"users": [], "posts": {}, "inventory": {}, "dims": S.PROFILE_DIMS}, allowed, as_of, outdir)
            return "no participants", 0
        inventories = TR.prepare_inventory(pd.read_parquet(cfg.inventory_file, columns=TR.INVENTORY_COLUMNS))
        data = S.build_spot(picks, rows, inventories, cfg.params, S.file_sha256(cfg.inventory_file))
        write_spot_files(data, allowed, as_of, outdir)
        note = f"{len(data['users'])} participants"
        return note + (f" (dwell not matched to a batch: {data['dwell_unmatched']})" if data["dwell_unmatched"] else ""), len(data["users"])
    except Exception as e:  # the spot check must never fail a pull
        return f"failed: {type(e).__name__}", 0


# ---- ids report (local only) -------------------------------------------------------------------------
def read_ids(path):
    """Yougov ids of a file, one per line, in order and without duplicates."""
    with open(path) as fh:
        return list(dict.fromkeys(l.strip() for l in fh if l.strip()))


def write_ids_report(cfg, source, sess, att, pulled_iso, ref, outdir):
    """OUTDIR/ids_report.md for the ids of IDS_FILE; returns a note. yougov_id is read only for these ids."""
    if not cfg.ids_file:
        return "no IDS_FILE"
    try:
        ids = read_ids(cfg.ids_file)
        found = []
        for cc in cfg.pulled_countries():
            m = source.yougov_ids(cc, ids)
            if len(m):
                found.append(m.assign(country=cc))
        ymap = pd.concat(found, ignore_index=True) if found else pd.DataFrame(columns=["user_id", "yougov_id", "country"])
        ids_df = ymap.merge(sess[["country", "user_id", "condition", "status", "total_min", "n_attempts"]], on=["country", "user_id"])
        stops = list(cfg.stop_codes.values())
        text = R.build_report(ids, ids_df, att, sess, pulled_iso, cfg.params["short_stay_s"], stops, ref)
        write_atomic(os.path.join(outdir, "ids_report.md"), text)
        return f"{len(ids_df)} of {len(ids)} ids found"
    except Exception as e:  # the report must never fail a pull
        return f"failed: {type(e).__name__}: {str(e)[:100]}"


# ---- one run -----------------------------------------------------------------------------------------
def run(cfg, pulled_ms=None, reader_cls=None):
    """One aggregation. Writes to cfg.outdir; returns a dict for the summary and the publish step."""
    if pulled_ms is None:
        pulled_ms = (int(pd.Timestamp(cfg.pulled_at).value // 1_000_000) if cfg.pulled_at
                     else int(datetime.now(timezone.utc).timestamp() * 1000))
    launch_at_ms = launch_ms(cfg.launch, cfg.tz)
    launch_iso = iso_utc(launch_at_ms)
    launch_cc = {cc: launch_ms(cfg.launch_of(cc), cfg.tz) for cc in cfg.countries}
    launch_cc_iso = {cc: iso_utc(v) for cc, v in launch_cc.items()}
    source, failures = make_source(cfg, reader_cls)
    visited, errors_long, status, failures = pull(cfg, source, failures, pulled_ms)
    if not any(s == "ok" for s in status.values()):
        raise NoDataError(f"no server returned data: {failures}")
    core_ok = [cc for cc, s in status.items() if s == "ok"]

    classified = C.classify(visited, errors_long, pulled_ms, cfg.session_min, cfg.ignore_codes, cfg.stop_codes)
    P = participants_frame(visited, errors_long, classified, cfg, launch_at_ms)

    os.makedirs(cfg.outdir, exist_ok=True)
    cache = D.load_cache(cfg.outdir)
    end_ms = pulled_ms + 24 * 3600 * 1000
    results, detail_status, detail_errors = D.run(cfg, source, P, launch_at_ms, end_ms, pulled_ms, core_ok, cache, launch_cc,
                                                   save=lambda: D.save_cache(cfg.outdir, cache))
    if results:
        D.save_cache(cfg.outdir, cache)
    P = apply_attempts(P, errors_long, cfg, results)
    P = apply_flags(P, results)
    ex_all = pd.concat([r["ex"] for r in results.values()], ignore_index=True) if results else None
    act = pd.concat([r["active"] for r in results.values() if r["active"] is not None], ignore_index=True) \
        if any(r["active"] is not None for r in results.values()) else None
    att = sess = None
    if results:
        rec_all = pd.concat([r["rec_attempts"] for r in results.values()], ignore_index=True)
        att = SS.attempts_table(P, ex_all, rec_all, errors_long)
        sess = SS.participants_table(P[P["country"].isin(results)], att, pulled_ms, cfg.params)
    P = O.add_outcomes(P, errors_long, sess, pulled_ms, cfg.stop_codes, cfg.params)
    inputs = cubes.Inputs(P=P, events=errors_long, ex=ex_all, active=act, launch_ms=launch_at_ms,
                          p=cfg.params, bin_minutes=cfg.bin_minutes, attempts=att, sessions=sess)

    prev_meta, prev_frames = previous_published(cfg.site_dir)
    frames, files_info = assemble(cfg, inputs, core_ok, detail_status, prev_meta, prev_frames,
                                  launch_iso, iso_utc(pulled_ms), launch_cc_iso)
    detail_prev = {cc: ((prev_meta or {}).get("detail", {}).get(cc) or {}).get("as_of") for cc in cfg.countries
                   if same_basis(prev_meta, cfg, launch_iso, cc, launch_cc_iso.get(cc))}
    spot_note, n_spot = write_spot(cfg, source, P, ex_all, detail_status, cfg.outdir, iso_utc(pulled_ms))
    spot_full = os.path.join(cfg.outdir, SPOT_FULL_FILE) if n_spot else None
    published = cfg.params["spot_publish"] == "on"
    if n_spot and published:
        spot_info = {"as_of": iso_utc(pulled_ms), "n_users": n_spot}
    else:   # nothing new: a copy published earlier stays (SPOT_PUBLISH on) or is removed (off)
        spot_info = (prev_meta or {}).get("spot") if published else None
    ref = sess.attrs.get("reference") if sess is not None else None
    meta = build_meta(cfg, pulled_ms, launch_at_ms, status, detail_status, detail_prev, files_info, classified,
                      launch_cc_iso, spot_info, ref)

    paths, sizes = {}, {}
    for name, frame in frames.items():
        paths[name] = os.path.join(cfg.outdir, name)
        write_atomic(paths[name], frame.to_csv(index=False))
        sizes[name] = os.path.getsize(paths[name])
    meta_path = os.path.join(cfg.outdir, "meta.json")
    write_atomic(meta_path, json.dumps(meta, indent=1) + "\n")
    write_atomic(os.path.join(cfg.outdir, "participants.csv"), P.drop(columns=["attempt"]).to_csv(index=False))
    ids_note = "off"
    if sess is not None:       # row level, local only
        write_atomic(os.path.join(cfg.outdir, "participants_sessions.csv"), sess.drop(columns=["attempt"], errors="ignore").round(3).to_csv(index=False))
        write_atomic(os.path.join(cfg.outdir, "attempts_local.csv"), att.round(3).to_csv(index=False))
        ids_note = write_ids_report(cfg, source, sess, att, meta["pulled_at"], ref, cfg.outdir)
    remove = []
    if published and n_spot:
        paths[SPOT_FILE] = os.path.join(cfg.outdir, SPOT_FILE)
        sizes[SPOT_FILE] = os.path.getsize(paths[SPOT_FILE])
    elif not published:
        remove.append(SPOT_FILE)
    if PREV_COUNTRY_FILE in frames:
        append_history(cfg.outdir, frames[PREV_COUNTRY_FILE], meta["pulled_at"], cfg.machine, meta["launch_utc"])
    return {"meta": meta, "meta_path": meta_path, "files": paths, "bins_path": paths.get(PREV_COUNTRY_FILE),
            "participants": classified, "failures": failures, "detail_status": detail_status,
            "detail_errors": detail_errors, "sizes": sizes, "spot": spot_note, "spot_full": spot_full,
            "remove": remove, "ids_report": ids_note}


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
        if info["status"] != "ok":
            row.update({"n": None, **{s: None for s in C.STATUSES}})
        rows.append(row)
    df = pd.DataFrame(rows)
    ok = df[df["status"] == "ok"]
    total = {"country": "ALL(ok)", "status": "", "n": int(ok["n"].sum())}
    total.update({s: int(ok[s].sum()) for s in C.STATUSES})
    return pd.concat([df, pd.DataFrame([total])], ignore_index=True)

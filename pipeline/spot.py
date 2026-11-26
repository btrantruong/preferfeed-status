"""User spot check (panel E): the participant list, the default picks, the full local file and the public one.

Pure functions. The batches, rewards and profiles of a participant come from trajectory.py.
  spot_users_full.json  every field of every listed participant; stays in OUTDIR
  spot_users.json       public_view of it: participants whose condition is not in SPOT_PROFILE_CONDITIONS have no
                        profile and reward fields; copied into data/ when SPOT_PUBLISH is on
violations() is the check publish.py runs on a file before and after it is public. It lists what such a participant
may hold, so a field added later is refused until it is listed here.
"""
import hashlib

import numpy as np
import pandas as pd

import trajectory as T

PROFILE_DIMS = T.DIMS
CONDITIONS = ["ATTENTION", "PREFERENCE", "RANDOM"]


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pick_defaults(cands, min_requests, spot_user=""):
    """One default participant per condition among the candidates of one country.

    cands: DataFrame user_id, condition, created_at, n_next_batch (done participants). The pick is the
    participant whose number of next_batch exchanges is closest to the median of the condition among those with
    at least min_requests, ties by earliest created_at. spot_user ("COUNTRY:ID") replaces the PREFERENCE pick
    when it is a candidate. Returns {condition: user_id}."""
    out = {}
    d = cands[cands["n_next_batch"] >= min_requests]
    for cond in CONDITIONS:
        c = d[d["condition"] == cond]
        if c.empty:
            continue
        med = c["n_next_batch"].median()
        pick = c.assign(gap=(c["n_next_batch"] - med).abs()).sort_values(["gap", "created_at"]).iloc[0]
        out[cond] = int(pick["user_id"])
    if spot_user:
        _, uid = spot_user.split(":", 1)
        if int(uid) in set(cands["user_id"]):
            out["PREFERENCE"] = int(uid)
    return out


def select_users(P, ex, p, country):
    """User ids of one country for the list: the most recent SPOT_MAX_USERS done participants with exchanges,
    plus the default picks. Returns (ids, defaults {condition: id})."""
    done = P[(P["country"] == country) & (P["status"] == "done")]
    if ex is None or ex.empty or done.empty:
        return [], {}
    e = ex[(ex["country"] == country) & (ex["attempt_id"] == ex["final_attempt"])]
    n_nb = e[e["endpoint"] == "next_batch"].groupby("user_id").size()
    has = set(e["user_id"])
    done = done[done["user_id"].isin(has)].assign(n_next_batch=lambda d: d["user_id"].map(n_nb).fillna(0))
    spot = p["spot_user"] if p["spot_user"].startswith(country + ":") else ""
    defaults = pick_defaults(done, p["spot_min_requests"], spot)
    recent = done.sort_values("created_at", ascending=False)["user_id"].head(p["spot_max_users"]).tolist()
    ids = list(dict.fromkeys(recent + list(defaults.values())))
    return [int(u) for u in ids], defaults


def exchanges_of_final_attempt(rows):
    """Rows of one participant from the last init on, in time order."""
    return T.split_attempts(rows)[-1]


def user_record(rows, inventory, p, posts):
    """The final attempt of one participant (trajectory.build_attempt); posts (dict) collects the posts served."""
    return T.build_attempt(exchanges_of_final_attempt(rows), inventory, p, posts)


def build_spot(picks, spot_rows, inventories, p, local_sha, inventory_note=None):
    """Assemble spot_users.json.

    picks: {country: (ids, defaults)} from select_users plus the participant info
           {country: DataFrame user_id, condition, created_at, n_next_batch}.
    spot_rows: {country: DataFrame (db.SPOT_COLUMNS)}. inventories: trajectory.prepare_inventory.
    local_sha: sha256 of the local inventory file. Returns the full data (every field, local use only; see
    public_view) as a dict that json.dump can write."""
    users, posts, inventory = [], {}, {}
    for cc, (ids, defaults, info) in picks.items():
        rows = spot_rows.get(cc)
        if rows is None or rows.empty or cc not in inventories:
            continue
        server = rows["inventory_sha256"].dropna()
        inventory[cc] = {"server_sha256": server.iloc[0] if len(server) else None, "local_sha256": local_sha}
        inventory[cc]["match"] = inventory[cc]["server_sha256"] == local_sha
        default_of = {u: c for c, u in defaults.items()}
        for uid in ids:
            g = rows[rows["user_id"] == uid]
            if g.empty:
                continue
            meta = info[info["user_id"] == uid].iloc[0]
            rec = user_record(g, inventories[cc], p, posts)
            users.append({"country": cc, "user_id": int(uid), "condition": meta["condition"],
                          "created_at": int(meta["created_at"]), "default_for": default_of.get(uid),
                          "n_next_batch": int(meta["n_next_batch"]), **rec})
    users.sort(key=lambda u: -u["created_at"])
    return {"users": users, "posts": posts, "inventory": inventory, "dims": PROFILE_DIMS,
            "batch_size": p["batch_size"], "note": inventory_note,
            "dwell_unmatched": sum(u["dwell_unmatched"] for u in users)}


# ---- the public file ---------------------------------------------------------------------------------
FULL_MARK = "local_full"   # key of the full file; the page shows a line for it and violations() refuses it
# what a participant outside SPOT_PROFILE_CONDITIONS may hold in the public file
HIDDEN_USER_KEYS = {"country", "user_id", "condition", "created_at", "default_for", "n_next_batch", "exchanges",
                    "t0_ms", "dwell_unmatched", "profile_hidden"}
HIDDEN_EXCHANGE_KEYS = {"request_index", "endpoint", "algo_type", "phase", "draw", "t_min", "signal_batch", "batches"}
HIDDEN_BATCH_KEYS = {"batch", "post_ids", "n_served", "mean_sum", "mean_centered", "dwell_ms"}


def public_view(data, allowed):
    """The data without the profile and reward fields of the participants outside `allowed`; same participants."""
    return {**data, "users": [T.hide_profile(u, u["condition"], allowed) for u in data["users"]]}


def violations(data, allowed):
    """Why a spot file must not be public: one line per problem, empty when it may be published.

    A participant is outside `allowed` when the condition, or the algorithm type of any request, is not in it."""
    if not isinstance(data, dict) or not isinstance(data.get("users"), list):
        return ["not a spot check file"]
    out = ["it is the full local file"] if data.get(FULL_MARK) else []
    for u in data["users"]:
        exchanges = u.get("exchanges", [])
        used = {u.get("condition")} | {e.get("algo_type") for e in exchanges if e.get("algo_type") is not None}
        if used <= set(allowed):
            continue
        extra = set(u) - HIDDEN_USER_KEYS
        for e in exchanges:
            extra |= set(e) - HIDDEN_EXCHANGE_KEYS
            for b in e.get("batches", []):
                extra |= set(b) - HIDDEN_BATCH_KEYS
        if extra:
            out.append(f"{u.get('country')} participant of condition {u.get('condition')} holds {', '.join(sorted(extra))}")
    return out

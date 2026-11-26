"""User spot check (public panel E): the participant list, the default picks and the published file.

Pure functions. The batches, rewards and profiles of a participant come from trajectory.py. The file is public
when SPOT_PUBLISH is on; participants whose condition is not in SPOT_PROFILE_CONDITIONS are listed without profile
and reward fields.
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
    local_sha: sha256 of the local inventory file. Participants whose condition is not in SPOT_PROFILE_CONDITIONS
    are listed without profile and reward fields. Returns a dict that json.dump can write."""
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
            rec = T.hide_profile(user_record(g, inventories[cc], p, posts), meta["condition"], p["spot_profile_conditions"])
            users.append({"country": cc, "user_id": int(uid), "condition": meta["condition"],
                          "created_at": int(meta["created_at"]), "default_for": default_of.get(uid),
                          "n_next_batch": int(meta["n_next_batch"]), **rec})
    users.sort(key=lambda u: -u["created_at"])
    return {"users": users, "posts": posts, "inventory": inventory, "dims": PROFILE_DIMS,
            "batch_size": p["batch_size"], "note": inventory_note,
            "dwell_unmatched": sum(u["dwell_unmatched"] for u in users)}

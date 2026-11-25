"""User spot check (panel D, local preview only): participant list, default picks, batches and post vectors.

Pure functions. The output (spot_users.json) holds one participant's data (u_long profile and the posts that
participant saw), so it is written to OUTDIR, never copied by publish.py and served by preview.py under
local/ only.

Batch numbers follow algo_exchange.served_batch (1-based): the init exchange serves 2 * BATCH_SIZE posts, which
are batches 1 and 2 (first and last BATCH_SIZE ids); a next_batch exchange serves one batch, numbered
algo_state.n_batches_served. u_long of an exchange is the profile after the signals of the previous batch,
and it is the profile that chose the batch of the same response when draw is "recommend".
"""
import hashlib

import numpy as np
import pandas as pd

PROFILE_DIMS = ["us_v_them", "fear", "outrage", "pride", "hope"]  # SCORE_COLS of preferfeed_algo, in this order
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
    rows = rows.reset_index(drop=True)
    inits = rows.index[rows["endpoint"] == "init"]
    return rows.loc[inits[-1]:] if len(inits) else rows


def nn(x):
    """None for a missing value (None or NaN), the value otherwise: JSON has no NaN."""
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else x


def cut_text(text, max_chars):
    t = "" if text is None else str(text)
    return (t[:max_chars], True) if len(t) > max_chars else (t, False)


def user_record(rows, inv, batch_size, max_chars, posts):
    """One participant's exchanges and batches; posts (dict) collects the posts that were served."""
    rows = exchanges_of_final_attempt(rows)
    t0 = rows["timestamp_server"].min()
    exchanges, last_batch = [], 0
    for r in rows.itertuples():
        ids = list(r.served_post_ids) if isinstance(r.served_post_ids, (list, tuple, np.ndarray)) else []
        chunks = [ids[k:k + batch_size] for k in range(0, len(ids), batch_size)]
        nb = r.n_batches_served
        first = int(nb) - len(chunks) + 1 if nb is not None and not pd.isna(nb) else last_batch + 1
        last_batch = first + len(chunks) - 1
        u = [None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)
             for v in (r.u_long if isinstance(r.u_long, (list, tuple, np.ndarray)) else [])]
        batches = []
        for k, chunk in enumerate(chunks):
            found = [i for i in chunk if i in inv.index]
            for i in found:
                if i not in posts:
                    row = inv.loc[i]
                    text, cut = cut_text(row["text"], max_chars)
                    posts[i] = {"country": row["country"], "platform": row["platform"],
                                "scores": [int(row[d]) for d in PROFILE_DIMS],
                                "sum": float(sum(int(row[d]) for d in PROFILE_DIMS)), "text": text, "cut": cut}
            sums = [posts[i]["sum"] for i in found]
            batches.append({"batch": first + k, "post_ids": found, "n_served": len(chunk),
                            "mean_sum": float(np.mean(sums)) if sums else None})
        exchanges.append({"request_index": None if r.request_index is None or pd.isna(r.request_index)
                          else int(r.request_index), "endpoint": r.endpoint, "phase": nn(r.phase), "draw": nn(r.draw),
                          "t_min": float((r.timestamp_server - t0) / 60_000), "u_long": u or None,
                          "u_long_sum": float(np.nansum([np.nan if v is None else v for v in u])) if u else None,
                          "batches": batches})
    return {"exchanges": exchanges, "t0_ms": int(t0)}


def build_spot(picks, spot_rows, inv_by_country, p, local_sha, inventory_note=None):
    """Assemble spot_users.json.

    picks: {country: (ids, defaults)} from select_users plus the participant info
           {country: DataFrame user_id, condition, created_at, n_next_batch}.
    spot_rows: {country: DataFrame (db.SPOT_COLUMNS)}. inv_by_country: {country: inventory indexed by post_id}.
    local_sha: sha256 of the local inventory file. Returns a dict that json.dump can write."""
    users, posts, inventory = [], {}, {}
    for cc, (ids, defaults, info) in picks.items():
        rows = spot_rows.get(cc)
        if rows is None or rows.empty:
            continue
        inv = inv_by_country.get(cc)
        server = rows["inventory_sha256"].dropna()
        inventory[cc] = {"server_sha256": server.iloc[0] if len(server) else None, "local_sha256": local_sha}
        inventory[cc]["match"] = inventory[cc]["server_sha256"] == local_sha
        default_of = {u: c for c, u in defaults.items()}
        for uid in ids:
            g = rows[rows["user_id"] == uid]
            if g.empty:
                continue
            rec = user_record(g, inv if inv is not None else pd.DataFrame(index=[]), p["batch_size"],
                              p["spot_text_max_chars"], posts) if inv is not None else None
            if rec is None:
                continue
            meta = info[info["user_id"] == uid].iloc[0]
            users.append({"country": cc, "user_id": int(uid), "condition": meta["condition"],
                          "created_at": int(meta["created_at"]), "default_for": default_of.get(uid),
                          "n_next_batch": int(meta["n_next_batch"]), **rec})
    users.sort(key=lambda u: -u["created_at"])
    return {"users": users, "posts": posts, "inventory": inventory, "dims": PROFILE_DIMS,
            "batch_size": p["batch_size"], "note": inventory_note}

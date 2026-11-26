"""One participant's attempt as batches, rewards and profiles. Pure functions, no DB access.

Used by the spot check (spot.py, public panel E) and by the local view (local_view.py).

Timing. A request carries the signals of batch signal_batch = t and returns batch t + 2 (served batch). Inside it:
reward r of the posts of batch t, u_short = sum r c / (sum |r| + eps), u_long = (1 - alpha) u_long + alpha u_short,
and u_long chooses the returned batch. c is the score vector of a post minus the inventory mean of the country.
The init request serves batches 1 and 2.

Rewards are not logged. They are rebuilt as preferfeed_algo does it (reward.py): only a request in phase algorithm
of the attention or preference condition has them.
  attention   z = (log(max(dwell, 1e-6) / words) - warmup_log_mu) / max(warmup_log_sigma, REWARD_SIGMA_FLOOR);
              +1 above REWARD_ETA, -1 below -REWARD_ETA, else 0; missing for a dwell that is not finite or
              below MIN_DWELL_MS
  preference  the vote (+1, 0, -1); missing without a vote
A post whose signals arrived before is left out. The profile is updated only if at least one reward is present;
u_short in the log keeps the last updating value otherwise, so it is reported only for updating requests.

Checks per attempt: u_short rebuilt equals the logged one (updating requests); u_long follows the update rule with
alpha, or is unchanged when the request did not update (every next_batch request with a logged previous one).
"""
import numpy as np
import pandas as pd

DIMS = ["us_v_them", "fear", "outrage", "pride", "hope"]  # SCORE_COLS of preferfeed_algo, in this order
REWARD_TYPES = ["ATTENTION", "PREFERENCE"]
INVENTORY_COLUMNS = ["post_id", "country", "platform", "text", "n_words"] + DIMS
# fields of an exchange that carry the profile or the rewards (and so, for the preference condition, the votes)
PROFILE_FIELDS = ["u_long", "u_long_sum", "u_long_norm", "u_short", "rewards", "updated"]
DWELL_FLOOR_MS = 1e-6


def nn(x):
    """None for a missing value (None or NaN), the value otherwise: JSON has no NaN."""
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else x


def as_list(x):
    return list(x) if isinstance(x, (list, tuple, np.ndarray)) else []


def vector(x):
    """A logged profile as floats with NaN for missing entries; None when there is none."""
    v = as_list(x)
    return np.array([np.nan if e is None else float(e) for e in v]) if v else None


def jsonable(v):
    return None if v is None else [None if np.isnan(e) else float(e) for e in v]


def cut_text(text, max_chars):
    t = "" if text is None else str(text)
    return (t[:max_chars], True) if len(t) > max_chars else (t, False)


def prepare_inventory(inventory):
    """{country: (posts indexed by post_id, mean score vector)} from the INVENTORY_COLUMNS of the inventory."""
    inv = inventory.drop_duplicates("post_id").set_index("post_id")
    return {cc: (g, g[DIMS].to_numpy(dtype=float).mean(axis=0)) for cc, g in inv.groupby("country")}


def split_attempts(rows):
    """The rows of one participant (time order) split at every init exchange; rows before the first init belong
    to the first part."""
    rows = rows.reset_index(drop=True)
    inits = rows.index[rows["endpoint"] == "init"].tolist()
    starts = [0] + inits[1:]
    return [rows.iloc[a:b] for a, b in zip(starts, starts[1:] + [len(rows)]) if b > a]


def request_rewards(algo_type, ids, dwell, preferences, words, mu, sigma, p):
    """Rewards (float, NaN = missing) of the posts `ids` of one request in phase algorithm, or None when the
    request has no reward (random condition, or an attention request without a baseline)."""
    if algo_type == "PREFERENCE":
        return np.array([np.nan if nn(v) is None else float(v) for v in preferences])
    if algo_type != "ATTENTION" or nn(mu) is None or nn(sigma) is None:
        return None
    d = np.array([np.nan if nn(v) is None else float(v) for v in dwell])
    usable = np.isfinite(d) & (d >= p["min_dwell_ms"])
    safe = np.where(usable, d, 1.0)
    log_w = np.log(np.maximum(safe, DWELL_FLOOR_MS)) - np.log(np.maximum(words, 1.0))
    z = (log_w - float(mu)) / max(float(sigma), p["reward_sigma_floor"])
    r = np.where(z > p["reward_eta"], 1.0, np.where(z < -p["reward_eta"], -1.0, 0.0))
    return np.where(usable, r, np.nan)


def centroid(rewards, centered, eps):
    """u_short of one request; missing rewards have weight 0."""
    w = np.where(np.isfinite(rewards), rewards, 0.0)
    return (w[:, None] * centered).sum(axis=0) / (np.abs(w).sum() + eps)


def dwell_by_batch(rows):
    """{batch: {post_id: dwell in ms}} from the signals: the exchange whose signal_batch is b carries the dwell of the
    posts of batch b (signal_post_ids and dwell_times have the same order). Exchanges without signal_batch,
    with lists of different length or with a missing dwell give nothing."""
    out = {}
    for r in rows.itertuples():
        b, ids, dw = getattr(r, "signal_batch", None), getattr(r, "signal_post_ids", None), getattr(r, "dwell_times", None)
        if b is None or pd.isna(b) or not isinstance(ids, (list, tuple, np.ndarray)) or not isinstance(dw, (list, tuple, np.ndarray)):
            continue
        if len(ids) != len(dw):
            continue
        out[int(b)] = {i: float(d) for i, d in zip(ids, dw) if d is not None and not pd.isna(d)}
    return out


def _post(posts, post_id, inv, mean, max_chars):
    if post_id not in posts:
        row = inv.loc[post_id]
        text, cut = cut_text(row["text"], max_chars)
        scores = [int(row[d]) for d in DIMS]
        posts[post_id] = {"country": row["country"], "platform": row["platform"], "scores": scores,
                          "centered": [round(float(s - m), 4) for s, m in zip(scores, mean)],
                          "sum": float(sum(scores)), "text": text, "cut": cut}
    return posts[post_id]


def build_attempt(rows, inventory, p, posts):
    """One attempt. rows: db.SPOT_COLUMNS in time order. inventory: (posts indexed by post_id, mean vector) of the
    country. p: batch_size, spot_text_max_chars, algo_alpha, algo_epsilon, reward_eta, reward_sigma_floor,
    min_dwell_ms, check_tol. posts (dict) collects the posts that were served."""
    inv, mean = inventory
    rows = rows.reset_index(drop=True)
    col = lambda r, name: getattr(r, name, None)
    t0 = rows["timestamp_server"].min()
    dwell = dwell_by_batch(rows)
    size, tol = p["batch_size"], p["check_tol"]

    # served batches of every request, and the posts of each batch
    exchanges, served, last_batch, unmatched = [], {}, 0, 0
    for r in rows.itertuples():
        ids = as_list(r.served_post_ids)
        chunks = [ids[k:k + size] for k in range(0, len(ids), size)]
        nb = r.n_batches_served
        first = int(nb) - len(chunks) + 1 if nb is not None and not pd.isna(nb) else last_batch + 1
        last_batch = first + len(chunks) - 1
        batches = []
        for k, chunk in enumerate(chunks):
            found = [i for i in chunk if i in inv.index]
            entries = [_post(posts, i, inv, mean, p["spot_text_max_chars"]) for i in found]
            dw = dwell.get(first + k, {})
            unmatched += len([i for i in dw if i not in chunk])
            centered = np.array([e["centered"] for e in entries], dtype=float)
            batches.append({"batch": first + k, "post_ids": found, "n_served": len(chunk),
                            "mean_sum": float(np.mean([e["sum"] for e in entries])) if entries else None,
                            "mean_centered": [round(float(v), 4) for v in centered.mean(axis=0)] if entries else None,
                            "dwell_ms": [dw.get(i) for i in found]})
            served[first + k] = found
        exchanges.append(batches)

    # rewards and profiles
    out, signalled, previous = [], set(), None
    checks = {"u_short": [0, 0], "u_long": [0, 0]}
    for r, batches in zip(rows.itertuples(), exchanges):
        u_long, u_short = vector(col(r, "u_long")), vector(col(r, "u_short"))
        sb = col(r, "signal_batch")
        sb = None if sb is None or pd.isna(sb) else int(sb)
        ids = as_list(col(r, "signal_post_ids"))
        dw, pref = as_list(col(r, "dwell_times")), as_list(col(r, "preferences"))
        keep = [k for k, i in enumerate(ids) if i in inv.index and i not in signalled]
        signalled.update(ids[k] for k in keep)
        rewards, updated = None, False
        if nn(col(r, "phase")) == "algorithm" and col(r, "algo_type") in REWARD_TYPES and keep:
            kept = [ids[k] for k in keep]
            words = inv.loc[kept, "n_words"].to_numpy(dtype=float)
            rw = request_rewards(col(r, "algo_type"), kept, [dw[k] if k < len(dw) else None for k in keep],
                                 [pref[k] if k < len(pref) else None for k in keep], words,
                                 col(r, "warmup_log_mu"), col(r, "warmup_log_sigma"), p)
            if rw is not None:
                by_id = {i: None if np.isnan(v) else int(v) for i, v in zip(kept, rw)}
                rewards = [by_id.get(i) for i in served.get(sb, [])]   # in the post order of the signal batch
                updated = bool(np.isfinite(rw).any())
                if updated and u_short is not None:
                    centered = inv.loc[kept, DIMS].to_numpy(dtype=float) - mean
                    rebuilt = centroid(rw, centered, p["algo_epsilon"])
                    checks["u_short"][0] += int(np.abs(rebuilt - u_short).max() <= tol)
                    checks["u_short"][1] += 1
        if r.endpoint != "init" and previous is not None and u_long is not None:
            a = p["algo_alpha"]
            expected = (1 - a) * previous + a * u_short if updated and u_short is not None else previous
            checks["u_long"][0] += int(np.abs(u_long - expected).max() <= tol)
            checks["u_long"][1] += 1
        previous = u_long
        out.append({
            "request_index": None if r.request_index is None or pd.isna(r.request_index) else int(r.request_index),
            "endpoint": r.endpoint, "algo_type": nn(col(r, "algo_type")), "phase": nn(r.phase), "draw": nn(r.draw),
            "t_min": float((r.timestamp_server - t0) / 60_000), "signal_batch": sb,
            "u_long": jsonable(u_long),
            "u_long_sum": None if u_long is None else float(np.nansum(u_long)),
            "u_long_norm": None if u_long is None else float(np.sqrt(np.nansum(u_long ** 2))),
            "u_short": jsonable(u_short) if updated else None, "updated": updated, "rewards": rewards,
            "batches": batches})
    return {"exchanges": out, "t0_ms": int(t0), "dwell_unmatched": int(unmatched), "checks": checks}


def hide_profile(record, condition, allowed):
    """The record without the profile and reward fields when the participant's condition, or the algorithm type of
    any request, is not in `allowed`. Posts, batch means and dwell stay."""
    used = {condition} | {e.get("algo_type") for e in record["exchanges"] if e.get("algo_type") is not None}
    if used <= set(allowed):
        return record
    exchanges = [{k: v for k, v in e.items() if k not in PROFILE_FIELDS} for e in record["exchanges"]]
    return {**{k: v for k, v in record.items() if k != "checks"}, "exchanges": exchanges, "profile_hidden": True}

"""trajectory.py: timing, rewards, profile checks, attempts and the published subset."""
import json

import numpy as np
import pandas as pd
import pytest

import config as cfgmod
import trajectory as T

P = {**cfgmod.default_params(), "batch_size": 2, "spot_text_max_chars": 100}
ALPHA = P["algo_alpha"]
IDS = list("abcdefghij")
SCORES = np.array([[(i * 7 + d * 3) % 4 for d in range(5)] for i in range(len(IDS))], dtype=float)
INV = pd.DataFrame({"post_id": IDS, "country": "UK", "platform": "X", "text": "t", "n_words": 10,
                    **{d: SCORES[:, k] for k, d in enumerate(T.DIMS)}})
INVENTORY = T.prepare_inventory(INV)["UK"]
CENTERED = SCORES - SCORES.mean(axis=0)


def session(condition, signals):
    """Rows of one session as the server logs them. signals: per request (dwell, preferences) of batch t = 1, 2, ...
    Batches have two posts; request t reports batch t and serves batch t + 2. mu = log(1000 / 10), sigma = 1."""
    batch = lambda t: IDS[2 * (t - 1): 2 * t]
    mu = float(np.log(1000) - np.log(10))
    rows = [dict(endpoint="init", timestamp_server=0, request_index=0, phase=None, draw="initial_feed", n_batches_served=2,
                 u_long=[0] * 5, u_short=[0] * 5, algo_type=condition, preferences=None, warmup_log_mu=None,
                 warmup_log_sigma=None, served_post_ids=batch(1) + batch(2), signal_post_ids=None, dwell_times=None, signal_batch=None)]
    u_long, u_short = np.zeros(5), np.zeros(5)
    for t, (dwell, pref) in enumerate(signals, start=1):
        warm = t < 2
        if not warm and condition != "RANDOM":
            if condition == "PREFERENCE":
                r = np.array([np.nan if v is None else v for v in pref], dtype=float)
            else:
                z = np.log(np.array(dwell, dtype=float)) - np.log(10) - mu
                r = np.where(np.array(dwell) >= 100, np.where(z > 0.25, 1.0, np.where(z < -0.25, -1.0, 0.0)), np.nan)
            if np.isfinite(r).any():
                w = np.where(np.isfinite(r), r, 0)
                u_short = (w[:, None] * CENTERED[2 * (t - 1): 2 * t]).sum(0) / (np.abs(w).sum() + 1e-8)
                u_long = (1 - ALPHA) * u_long + ALPHA * u_short
        att = condition == "ATTENTION" and not warm
        rows.append(dict(endpoint="next_batch", timestamp_server=t * 1000, request_index=t, phase="warmup" if warm else "algorithm",
                         draw="recommend", n_batches_served=t + 2, u_long=u_long.tolist(), u_short=u_short.tolist(),
                         algo_type=condition, preferences=pref, warmup_log_mu=mu if att else None, warmup_log_sigma=1.0 if att else None,
                         served_post_ids=batch(t + 2), signal_post_ids=batch(t), dwell_times=dwell, signal_batch=t))
    return pd.DataFrame(rows)


ATT = [([1000, 1000], [None, None]), ([5000, 200], [None, None]), ([1000, 50], [None, None])]


def test_attention_rewards_profile_and_checks():
    rec = T.build_attempt(session("ATTENTION", ATT), INVENTORY, P, {})
    ex = rec["exchanges"]
    assert ex[1]["rewards"] is None and not ex[1]["updated"]                      # warm-up batch
    assert ex[2]["rewards"] == [1, -1] and ex[2]["updated"] and ex[2]["signal_batch"] == 2
    assert ex[2]["batches"][-1]["batch"] == 4                                      # signals of batch t, batch t + 2 served
    assert ex[3]["rewards"] == [0, None] and ex[3]["updated"]                      # a dwell below 100 ms is missing
    assert rec["checks"] == {"u_short": [2, 2], "u_long": [3, 3]}
    json.dumps(rec, allow_nan=False)


def test_wrong_alpha_fails_the_u_long_check_only():
    rec = T.build_attempt(session("ATTENTION", ATT), INVENTORY, {**P, "algo_alpha": 0.7}, {})
    assert rec["checks"]["u_short"] == [2, 2] and rec["checks"]["u_long"][0] < rec["checks"]["u_long"][1]


def test_preference_votes_are_the_rewards():
    rec = T.build_attempt(session("PREFERENCE", [([1, 1], [1, 1]), ([1, 1], [1, None]), ([1, 1], [None, None])]), INVENTORY, P, {})
    ex = rec["exchanges"]
    assert ex[2]["rewards"] == [1, None] and ex[3]["rewards"] == [None, None]
    assert not ex[3]["updated"] and ex[3]["u_short"] is None and ex[3]["u_long"] == ex[2]["u_long"]
    assert rec["checks"] == {"u_short": [1, 1], "u_long": [3, 3]}


def test_random_has_no_reward_and_a_zero_profile():
    rec = T.build_attempt(session("RANDOM", ATT), INVENTORY, P, {})
    assert all(e["rewards"] is None and e["u_short"] is None for e in rec["exchanges"])
    assert rec["checks"] == {"u_short": [0, 0], "u_long": [3, 3]}


def test_batch_means_are_centered_on_the_inventory():
    posts = {}
    rec = T.build_attempt(session("RANDOM", ATT), INVENTORY, P, posts)
    b = rec["exchanges"][0]["batches"][1]
    assert b["batch"] == 2 and b["mean_centered"] == pytest.approx(CENTERED[2:4].mean(0), abs=1e-4)
    assert posts["c"]["centered"] == pytest.approx(CENTERED[2], abs=1e-4)


def test_a_repeated_signal_is_dropped():
    rows = session("ATTENTION", ATT)
    rows.at[3, "signal_post_ids"] = rows.at[2, "signal_post_ids"]                 # request 3 repeats batch 2
    rec = T.build_attempt(rows, INVENTORY, P, {})
    assert not rec["exchanges"][3]["updated"]


def test_split_attempts_at_every_init():
    a, b = session("RANDOM", ATT[:1]), session("RANDOM", ATT[:2])
    parts = T.split_attempts(pd.concat([a, b], ignore_index=True))
    assert [len(x) for x in parts] == [2, 3] and parts[1].iloc[0]["endpoint"] == "init"


def test_excluded_condition_has_no_profile_reward_or_vote():
    rec = T.build_attempt(session("PREFERENCE", [([1, 1], [1, 1]), ([1, 1], [1, -1])]), INVENTORY, P, {})
    out = T.hide_profile(rec, "PREFERENCE", ["ATTENTION", "RANDOM"])
    text = json.dumps(out)
    assert out["profile_hidden"] and "checks" not in out
    assert not any(f'"{k}"' in text for k in T.PROFILE_FIELDS + ["preferences"])
    assert out["exchanges"][2]["batches"][0]["mean_centered"] is not None
    assert T.hide_profile(rec, "PREFERENCE", ["PREFERENCE"]) is rec
    # a participant listed under another condition whose requests ran as preference is hidden too
    assert T.hide_profile(rec, "RANDOM", ["ATTENTION", "RANDOM"])["profile_hidden"]

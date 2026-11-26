"""Panel A outcomes: every category, the retry trigger and the order cases."""
import pandas as pd

import config as cfgmod
import outcomes as O

P0 = cfgmod.default_params()
STOPS = {"bot": "AUTOMATED_BROWSER_DETECTED", "idle": "IDLE_DETECTED", "reload": "PAGE_RELOAD_DETECTED"}
MIN = 60_000
T = 1_000_000_000_000
IDLE, RELOAD, BOT, RESTART = "IDLE_DETECTED", "PAGE_RELOAD_DETECTED", "AUTOMATED_BROWSER_DETECTED", "TIMELINE_RESTARTED"


def one(status="incomplete", log=(), now=60, started=True, sessions=None):
    """log: [(minute after creation, code)]. Returns the outcome columns of one participant."""
    P = pd.DataFrame([{"country": "UK", "user_id": 1, "created_at": T, "status": status, "started": started}])
    ev = pd.DataFrame([{"country": "UK", "user_id": 1, "pos": i, "code": c, "ts": T + int(m * MIN)}
                       for i, (m, c) in enumerate(log)], columns=["country", "user_id", "pos", "code", "ts"])
    return O.add_outcomes(P, ev, sessions, T + now * MIN, STOPS, P0).iloc[0][O.COLUMNS].to_dict()


def test_done_first_try_and_after_retry():
    assert one("done")["outcome"] == "done_first"
    r = one("done", [(2, IDLE), (3, RESTART)])
    assert (r["outcome"], r["retries"], r["trigger"], r["retry_outcome"]) == ("done_retry", 1, "idle", "done")


def test_left_without_error_and_ignored_codes():
    assert one()["outcome"] == "left_no_error"
    assert one(log=[(1, "NOT_FOUND"), (2, "SUPERSEDED_ATTEMPT")])["outcome"] == "left_no_error"
    r = one(log=[(2, RESTART), (3, "DUPLICATE_PARTICIPATION_ATTEMPT")])
    assert (r["outcome"], r["trigger"], r["retry_outcome"], r["last_error"]) == (
        "left_no_error_retried", "none", "left_no_final_error", "none")


def test_error_without_retry_includes_a_clean_restart_before_it():
    r = one(log=[(1, "SERVER_ERROR")])
    assert (r["outcome"], r["last_error"], r["retries"], r["retry_outcome"]) == ("left_error_no_retry", "server", 0, "")
    r = one(log=[(2, RESTART), (3, "CLIENT_FEED_INIT_FAILED")])
    assert (r["outcome"], r["last_error"], r["trigger"], r["retry_outcome"]) == (
        "left_error_no_retry", "client", "none", "left_final_error")


def test_retried_after_error_and_last_attempt():
    r = one(log=[(1, RELOAD), (2, RESTART)])
    assert (r["outcome"], r["last_error"], r["retry_outcome"]) == ("left_retried_after_error", "reload", "left_no_final_error")
    r = one(log=[(1, RELOAD), (2, RESTART), (3, "LOG_WRITE_FAILED")])
    assert (r["outcome"], r["last_error"], r["retry_outcome"]) == ("left_retried_after_error", "other", "left_final_error")


def test_trigger_is_from_the_attempt_ended_by_the_last_restart():
    r = one("done", [(1, IDLE), (2, RESTART), (4, RESTART)])
    assert (r["retries"], r["trigger"]) == (2, "none")
    r = one("done", [(1, IDLE), (2, RESTART), (3, "SERVER_ERROR"), (3.5, RELOAD), (4, RESTART)])
    assert r["trigger"] == "reload"


def test_log_order_is_by_time_not_position():
    r = one(log=[(3, RESTART), (1, IDLE)])
    assert (r["outcome"], r["trigger"]) == ("left_retried_after_error", "idle")


def test_cancelled_is_left_and_counts_as_error_without_a_code():
    r = one("cancelled", now=1)
    assert (r["outcome"], r["last_error"]) == ("left_error_no_retry", "other")
    assert one("cancelled", [(0.5, RELOAD)], now=1)["last_error"] == "reload"


def test_bot_block_at_creation_then_start_is_a_retry():
    r = one("done", [(0, BOT)])
    assert (r["outcome"], r["retries"], r["trigger"]) == ("done_retry", 1, "bot")
    assert one("cancelled", [(0, BOT)], started=False)["outcome"] == "left_error_no_retry"
    # a bot entry later than the creation is not a blocked first start
    assert one("done", [(5, BOT)])["outcome"] == "done_first"


def test_in_session_from_the_last_start_without_a_detail_pull():
    fallback = P0["session_ref_fallback_min"]
    assert one(now=fallback - 1)["outcome"] == "in_session"
    assert one(now=fallback)["outcome"] == "left_no_error"
    r = one(log=[(30, RESTART)], now=31)
    assert (r["outcome"], r["retry_outcome"]) == ("in_session", "in_session")


def test_session_state_of_the_detail_pull_decides():
    sess = pd.DataFrame([{"country": "UK", "user_id": 1, "state": "left"}])
    assert one(now=1, sessions=sess)["outcome"] == "left_no_error"
    sess["state"] = "in_session"
    assert one(now=600, sessions=sess)["outcome"] == "in_session"


def test_empty_input_has_the_columns():
    P = pd.DataFrame(columns=["country", "user_id", "created_at", "status", "started"])
    out = O.add_outcomes(P, pd.DataFrame(columns=["country", "user_id", "pos", "code", "ts"]), None, T, STOPS, P0)
    assert list(out.columns[-len(O.COLUMNS):]) == O.COLUMNS and out.empty

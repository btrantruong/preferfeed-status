"""One builder per published file. Pure functions: tables in, the published frame out.

REGISTRY maps each file to its columns, its window kind and its builder:
  window "created"  one row counts participants in a bin of BIN_MINUTES by session creation (created_at)
  window "event"    one row counts events in a bin of EVENT_BIN_MINUTES by the event's time
Only non-zero rows are written, bin_start is UTC ISO 8601, and no id-like column is ever published.
The registry also drives meta.json (the page reads the file list from there), carry-over, publish and preview.

Inputs of a builder (class Inputs):
  P       one row per participant: country, user_id, created_at (ms), created_bin (ms), status, reason,
          condition, started, viewed_posts, starts (timeline starts, NaN if unknown), after_stop,
          has_server_error, and for done participants the flags, requests, n_records (detail pull)
  events  errors_long: country, user_id, pos, code, detail, timestamp_server, ts (ms)
  ex      exchanges with attempt_id and final_attempt (detail pull) or None
  active  country, bin_ms, n_active (detail pull, full) or None
"""
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import pandas as pd

import checks

FLOW_NODES = ["SERVER_ERROR", "NOT_FOUND", "DUPLICATE_PARTICIPATION_ATTEMPT", "PAGE_RELOAD_DETECTED",
              "IDLE_DETECTED", "client failure", "AUTOMATED_BROWSER_DETECTED", "TIMELINE_RESTARTED"]
FLOW_OTHER, FLOW_START, FLOW_END = "other", "START", "END"
AGE_CODES_EXTRA = ["CLIENT_FEED_INIT_FAILED", "CLIENT_FEED_BATCH_LOAD_FAILED", "CLIENT_TRACKING_SEND_FAILED"]


@dataclass
class Inputs:
    P: pd.DataFrame
    events: pd.DataFrame
    ex: Optional[pd.DataFrame]
    active: Optional[pd.DataFrame]
    launch_ms: int
    p: dict            # Config.params
    bin_minutes: int
    attempts: Optional[pd.DataFrame] = None   # sessions.attempts_table (detail pull) or None
    sessions: Optional[pd.DataFrame] = None   # sessions.participants_table or None


@dataclass(frozen=True)
class Spec:
    name: str
    window: str        # created | event
    columns: list
    build: Callable
    coverage: str      # core | attempts | detail | full
    help: str = ""


def iso(ms):
    s = pd.to_datetime(pd.Series(np.asarray(ms, dtype="int64")), unit="ms", utc=True)
    return s.dt.strftime("%Y-%m-%dT%H:%M:%SZ").to_numpy()


def event_bin(ts_ms, launch_ms, bin_minutes):
    b = bin_minutes * 60_000
    return launch_ms + ((np.asarray(ts_ms, dtype="int64") - launch_ms) // b) * b


def count(df, keys, columns, name="n"):
    """Group-count df by keys (bin keys in ms) and return the published frame: bin_start as ISO, sorted."""
    if df.empty:
        return pd.DataFrame(columns=columns)
    out = df.groupby(keys, dropna=False).size().rename(name).reset_index()
    out["bin_start"] = iso(out["bin_ms"])
    out = out.drop(columns="bin_ms")[columns]
    return out.sort_values(columns[:-1]).reset_index(drop=True)


def with_bin(df, col="created_bin"):
    return df.assign(bin_ms=df[col])


# ---- core files ------------------------------------------------------------------------------------
def status_bins(i):
    return count(with_bin(i.P), ["bin_ms", "country", "status", "reason"],
                 ["bin_start", "country", "status", "reason", "n"])


def status_detail(i):
    d = with_bin(i.P)
    d["condition"] = d["condition"].fillna("unknown")
    d["started"] = d["started"].map(lambda x: 1 if x is True or x == 1 else 0)
    d["has_server_error"] = d["has_server_error"].astype(int)
    return count(d, ["bin_ms", "country", "condition", "started", "has_server_error", "status", "reason"],
                 ["bin_start", "country", "condition", "started", "has_server_error", "status", "reason", "n"])


def attempts(i):
    d = i.P[i.P["starts"].notna()].copy()
    d["attempts"] = np.minimum(d["starts"], i.p["attempts_max"]).astype(int)
    d["after_stop"] = d["after_stop"].astype(int)
    return count(with_bin(d), ["bin_ms", "country", "status", "attempts", "after_stop"],
                 ["bin_start", "country", "status", "attempts", "after_stop", "n"])


def clean_detail(code, detail):
    """Details are free text: SERVER_ERROR keeps an exception class name, client codes keep 'HTTP nnn'."""
    s = "" if detail is None or (isinstance(detail, float) and pd.isna(detail)) else str(detail)
    if code.startswith("CLIENT_"):
        import re
        m = re.search(r"HTTP (\d{3})", s)
        return f"HTTP {m.group(1)}" if m else "other"
    import re
    return s if re.fullmatch(r"[A-Za-z0-9_]{1,60}", s) else "other"


def errors_time(i):
    codes = [i.p["server_error_code"]] + list(i.p["client_error_codes"])
    d = i.events[i.events["code"].isin(codes) & i.events["ts"].notna()].copy()
    if d.empty:
        return pd.DataFrame(columns=["bin_start", "country", "code", "detail", "n"])
    d["detail"] = [clean_detail(c, x) for c, x in zip(d["code"], d["detail"])]
    d["bin_ms"] = event_bin(d["ts"], i.launch_ms, i.p["event_bin_minutes"])
    return count(d, ["bin_ms", "country", "code", "detail"], ["bin_start", "country", "code", "detail", "n"])


def errors_age(i):
    codes = [i.p["server_error_code"]] + list(i.p["client_error_codes"])
    d = i.events[i.events["code"].isin(codes) & i.events["ts"].notna()].merge(
        i.P[["country", "user_id", "created_at", "created_bin"]], on=["country", "user_id"])
    if d.empty:
        return pd.DataFrame(columns=["bin_start", "country", "code", "age_bin", "n"])
    w, top = i.p["error_age_bin_min"] * 60_000, i.p["error_age_max_min"] // i.p["error_age_bin_min"]
    d["age_bin"] = np.clip((d["ts"] - d["created_at"]) // w, 0, top).astype(int)
    return count(with_bin(d), ["bin_ms", "country", "code", "age_bin"],
                 ["bin_start", "country", "code", "age_bin", "n"])


def error_node(code, client_codes):
    if code in client_codes:
        return "client failure"
    return code if code in FLOW_NODES else FLOW_OTHER


def error_runs(events, exclude, client_codes):
    """{(country, user_id): [node, ...]}: codes ordered by timestamp_server (ties by position in the log),
    mapped to flow nodes, consecutive repeats merged into one run."""
    ev = events[~events["code"].isin(list(exclude)) & events["ts"].notna()]
    runs = {}
    for key, g in ev.sort_values(["country", "user_id", "ts", "pos"], kind="stable").groupby(
            ["country", "user_id"], sort=False):
        nodes = []
        for code in g["code"]:
            node = error_node(code, client_codes)
            if not nodes or nodes[-1] != node:
                nodes.append(node)
        runs[key] = nodes
    return runs


def error_flow(i):
    runs = error_runs(i.events, i.p.get("flow_exclude_codes", []), set(i.p["client_error_codes"]))
    created = dict(zip(zip(i.P["country"], i.P["user_id"]), i.P["created_bin"]))
    rows = []
    for key, s in runs.items():
        if key not in created:
            continue
        cc, b = key[0], created[key]
        rows.append((b, cc, 0, FLOW_START, s[0]))
        for k in range(1, i.p["flow_steps"]):
            if len(s) >= k + 1:
                rows.append((b, cc, k, s[k - 1], s[k]))
            elif len(s) == k:
                rows.append((b, cc, k, s[k - 1], FLOW_END))
    d = pd.DataFrame(rows, columns=["bin_ms", "country", "step", "from_node", "to_node"])
    return count(d, ["bin_ms", "country", "step", "from_node", "to_node"],
                 ["bin_start", "country", "step", "from_node", "to_node", "n"])


# ---- detail files ----------------------------------------------------------------------------------
def hist_bin(values, width, vmax):
    """0 for exactly 0, then the lower edges 1, width, 2 width, ... and vmax for the open last bin."""
    v = np.asarray(values)
    b = np.where(v <= 0, 0, np.where(v < width, 1, (v // width) * width))
    return np.minimum(b, vmax).astype(int)


def done_with_flags(i):
    d = i.P[(i.P["status"] == "done") & i.P["n_records"].notna()]
    return d


def flags(i):
    d = done_with_flags(i)
    if d.empty:
        return pd.DataFrame(columns=["bin_start", "country", "n_done"] + checks.ALL_FLAGS + ["any_fail"])
    d = with_bin(d).assign(n_done=1)
    d["any_fail"] = d[checks.FAIL_FLAGS].any(axis=1)
    cols = ["n_done"] + checks.ALL_FLAGS + ["any_fail"]
    g = d.groupby(["bin_ms", "country"])[cols].sum().astype("int64").reset_index()
    g["bin_start"] = iso(g["bin_ms"])
    return g[["bin_start", "country"] + cols].sort_values(["bin_start", "country"]).reset_index(drop=True)


def records_hist(i):
    d = done_with_flags(i)
    d = with_bin(d).assign(records_bin=hist_bin(d["n_records"], i.p["records_bin_width"], i.p["records_max"]))
    return count(d, ["bin_ms", "country", "records_bin"], ["bin_start", "country", "records_bin", "n"])


def requests_hist(i):
    d = done_with_flags(i)
    d = d[d["requests"].notna()]
    d = with_bin(d).assign(requests_bin=np.minimum(d["requests"], i.p["requests_max"]).astype(int))
    d["condition"] = d["condition"].fillna("unknown")
    out = count(d, ["bin_ms", "country", "condition", "requests_bin"],
                ["bin_start", "country", "condition", "requests_bin", "n"])
    return out.rename(columns={"requests_bin": "requests"})


def requests_diff_hist(i):
    d = done_with_flags(i)
    d = d[d["requests"].notna() & d["viewed_posts"].notna()]
    r = d["requests"].astype(float) - d["viewed_posts"].astype(float) / i.p["batch_size"]
    d = with_bin(d).assign(diff_bin=np.clip(np.floor(r + 0.5), -i.p["diff_range"], i.p["diff_range"]).astype(int))
    d["condition"] = d["condition"].fillna("unknown")
    out = count(d, ["bin_ms", "country", "condition", "diff_bin"],
                ["bin_start", "country", "condition", "diff_bin", "n"])
    return out.rename(columns={"diff_bin": "diff"})


def algo_calls(i):
    if i.ex is None or i.ex.empty:
        return pd.DataFrame(columns=["bin_start", "country", "endpoint", "n"])
    d = i.ex.assign(bin_ms=event_bin(i.ex["timestamp_server"], i.launch_ms, i.p["event_bin_minutes"]))
    return count(d, ["bin_ms", "country", "endpoint"], ["bin_start", "country", "endpoint", "n"])


def active(i):
    if i.active is None or i.active.empty:
        return pd.DataFrame(columns=["bin_start", "country", "n_active"])
    a = i.active[i.active["n_active"] > 0].copy()
    a["bin_start"] = iso(a["bin_ms"])
    return a[["bin_start", "country", "n_active"]].sort_values(["bin_start", "country"]).reset_index(drop=True)


def warmup(i):
    if i.ex is None or i.ex.empty:
        return pd.DataFrame(columns=["bin_start", "country", "condition", "request_index", "n", "n_algorithm"])
    nb = i.ex[(i.ex["endpoint"] == "next_batch") & (i.ex["attempt_id"] == i.ex["final_attempt"])].merge(
        i.P[["country", "user_id", "condition", "created_bin"]], on=["country", "user_id"])
    nb = nb[(nb["condition"].notna()) & (nb["condition"] != "RANDOM")
            & nb["request_index"].between(1, i.p["warmup_max_index"])].copy()
    if nb.empty:
        return pd.DataFrame(columns=["bin_start", "country", "condition", "request_index", "n", "n_algorithm"])
    nb["request_index"] = nb["request_index"].astype(int)
    nb["is_algorithm"] = (nb["phase"] == "algorithm").astype(int)
    g = nb.groupby(["created_bin", "country", "condition", "request_index"]).agg(
        n=("endpoint", "size"), n_algorithm=("is_algorithm", "sum")).reset_index()
    g["bin_start"] = iso(g["created_bin"])
    return g[["bin_start", "country", "condition", "request_index", "n", "n_algorithm"]].sort_values(
        ["bin_start", "country", "condition", "request_index"]).reset_index(drop=True)


# ---- sessions: in session or left, time on the feed, attempt durations (detail pull) -------------------
def dur_bin(minutes, edges_s):
    """Bin of a duration: 0 below the first edge, k from the k-th edge on, len(edges) for the open last bin."""
    return np.searchsorted(np.asarray(edges_s, dtype="float64"), np.asarray(minutes, dtype="float64") * 60, side="right").astype(int)


def _sessions(i):
    s = i.sessions
    return None if s is None or s.empty or "state" not in s else s


def session_state(i):
    cols = ["bin_start", "country", "condition", "state", "n", "n_disagree"]
    s = _sessions(i)
    if s is None:
        return pd.DataFrame(columns=cols)
    d = s.assign(bin_ms=s["created_bin"], condition=s["condition"].fillna("unknown"), n_disagree=s["disagree"].astype(int))
    g = d.groupby(["bin_ms", "country", "condition", "state"]).agg(n=("state", "size"), n_disagree=("n_disagree", "sum")).reset_index()
    g["bin_start"] = iso(g["bin_ms"])
    return g[cols].sort_values(cols[:4]).reset_index(drop=True)


def time_on_feed_hist(i):
    cols = ["bin_start", "country", "condition", "measure", "group", "dur_bin", "n", "sum_min"]
    s = _sessions(i)
    if s is None:
        return pd.DataFrame(columns=cols)
    d = s[s["last_record_ms"].notna() & (s["n_attempts"] >= 1)]
    parts = []
    for measure, col in (("final_attempt", "final_min"), ("total", "total_min")):
        x = d[d[col].notna()]
        parts.append(pd.DataFrame({"bin_ms": x["created_bin"], "country": x["country"], "condition": x["condition"].fillna("unknown"),
                                   "measure": measure, "group": np.where(x["status"] == "done", "done", "not_done"),
                                   "dur_bin": dur_bin(x[col], i.p["duration_edges_s"]), "min": x[col]}))
    d = pd.concat(parts, ignore_index=True)
    if d.empty:
        return pd.DataFrame(columns=cols)
    g = d.groupby(["bin_ms", "country", "condition", "measure", "group", "dur_bin"]).agg(n=("min", "size"), sum_min=("min", "sum")).reset_index()
    g["bin_start"] = iso(g["bin_ms"]); g["sum_min"] = g["sum_min"].round(3)
    return g[cols].sort_values(cols[:6]).reset_index(drop=True)


def attempts_hist(i):
    cols = ["bin_start", "country", "attempt_no", "ends_as", "dur_bin", "n", "sum_min"]
    s = _sessions(i)
    if i.attempts is None or i.attempts.empty or s is None:
        return pd.DataFrame(columns=cols)
    a = i.attempts[i.attempts["duration_min"].notna()].merge(s[["country", "user_id", "created_bin"]], on=["country", "user_id"])
    if a.empty:
        return pd.DataFrame(columns=cols)
    a = a.assign(bin_ms=a["created_bin"], attempt_no=np.minimum(a["attempt"], i.p["attempts_max"]).astype(int),
                 dur_bin=dur_bin(a["duration_min"], i.p["duration_edges_s"]))
    g = a.groupby(["bin_ms", "country", "attempt_no", "ends_as", "dur_bin"]).agg(n=("duration_min", "size"), sum_min=("duration_min", "sum")).reset_index()
    g["bin_start"] = iso(g["bin_ms"]); g["sum_min"] = g["sum_min"].round(3)
    return g[cols].sort_values(cols[:5]).reset_index(drop=True)


REGISTRY = [
    Spec("status_bins.csv", "created", ["bin_start", "country", "status", "reason", "n"], status_bins, "core"),
    Spec("status_detail.csv", "created",
         ["bin_start", "country", "condition", "started", "has_server_error", "status", "reason", "n"],
         status_detail, "core"),
    Spec("attempts.csv", "created", ["bin_start", "country", "status", "attempts", "after_stop", "n"],
         attempts, "attempts"),
    Spec("errors_time.csv", "event", ["bin_start", "country", "code", "detail", "n"], errors_time, "core"),
    Spec("errors_age.csv", "created", ["bin_start", "country", "code", "age_bin", "n"], errors_age, "core"),
    Spec("error_flow.csv", "created", ["bin_start", "country", "step", "from_node", "to_node", "n"],
         error_flow, "core"),
    Spec("flags.csv", "created",
         ["bin_start", "country", "n_done"] + checks.ALL_FLAGS + ["any_fail"], flags, "detail"),
    Spec("records_hist.csv", "created", ["bin_start", "country", "records_bin", "n"], records_hist, "detail"),
    Spec("requests_hist.csv", "created", ["bin_start", "country", "condition", "requests", "n"],
         requests_hist, "detail"),
    Spec("requests_diff_hist.csv", "created", ["bin_start", "country", "condition", "diff", "n"],
         requests_diff_hist, "detail"),
    Spec("algo_calls.csv", "event", ["bin_start", "country", "endpoint", "n"], algo_calls, "detail"),
    Spec("active.csv", "event", ["bin_start", "country", "n_active"], active, "full"),
    Spec("warmup.csv", "created",
         ["bin_start", "country", "condition", "request_index", "n", "n_algorithm"], warmup, "detail"),
    Spec("session_state.csv", "created", ["bin_start", "country", "condition", "state", "n", "n_disagree"],
         session_state, "detail"),
    Spec("time_on_feed_hist.csv", "created",
         ["bin_start", "country", "condition", "measure", "group", "dur_bin", "n", "sum_min"], time_on_feed_hist, "detail"),
    Spec("attempts_hist.csv", "created", ["bin_start", "country", "attempt_no", "ends_as", "dur_bin", "n", "sum_min"],
         attempts_hist, "detail"),
]
BY_NAME = {s.name: s for s in REGISTRY}
FILE_NAMES = [s.name for s in REGISTRY]
# published columns that look like identifiers (a test fails on any of them)
ID_LIKE = ("id", "user_id", "yougov_id", "post_id", "participant", "session")

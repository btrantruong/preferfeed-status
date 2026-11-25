"""Reads from the study databases (read-only) or from an export folder (replay).

The DB reader (SubsetReader) is imported from PFDA_DIR (config.local.env), since its path differs by
machine. Engines are built from creds.yml with CREDS_KEYS (country -> key), so no aliased temp creds file is
written.

Two sources answer the same questions, so that builders, tests and page checks run without a database:
  LiveSource    the core pull through the reader, and the detail queries (Q1 to Q4) as read-only SQL
  ExportSource  the same tables from CC/window/table.parquet (the layout of the preferfeed_dataaccess exports)

Detail queries. Every statement is a SELECT (checked before it is sent) in a read-only transaction with a
statement timeout. record_entry has only its primary key as an index, so its queries are bounded by record_id:
the lower bound is found by bisection on timestamp_server through the primary key (rows are inserted in
time order). participant_contact is never read.
"""
import glob
import json
import os
import sys

import pandas as pd
import yaml

REQUIRED_COLUMNS = ["id", "created_at", "done", "cancelled", "errors"]
OPTIONAL_COLUMNS = ["condition", "started", "viewed_posts", "attempt"]
COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS
EXCHANGE_COLUMNS = ["user_id", "endpoint", "algo_type", "timestamp_server", "request_index", "phase"]
SPOT_COLUMNS = ["user_id", "endpoint", "timestamp_server", "request_index", "phase", "draw",
                "n_batches_served", "u_long", "served_post_ids", "signal_post_ids", "dwell_times", "signal_batch",
                "inventory_sha256"]

# ---- SQL (all SELECT) ------------------------------------------------------------------------------
SQL_COLUMNS = ("SELECT column_name FROM information_schema.columns WHERE table_name = :t")
SQL_ID_RANGE = "SELECT min(record_id) AS lo, max(record_id) AS hi FROM record_entry"
SQL_ID_PROBE = ("SELECT timestamp_server AS t FROM record_entry WHERE record_id >= :m "
                "ORDER BY record_id LIMIT 1")
SQL_EXCHANGES = ("SELECT a.user_id, a.endpoint, a.algo_type, a.timestamp_server, "
                 "NULLIF(a.algo_state->>'request_index', '')::int AS request_index, "
                 "a.algo_state->>'phase' AS phase{attempt} "
                 "FROM algo_exchange a JOIN visited_users u ON u.id = a.user_id "
                 "WHERE u.created_at >= :start AND u.created_at < :end")
SQL_RECORD_COUNTS = ("SELECT r.user_id, count(*) AS n FROM record_entry r "
                     "JOIN unnest(CAST(:uids AS integer[]), CAST(:since AS bigint[])) AS t(uid, since) "
                     "ON r.user_id = t.uid AND r.timestamp_server >= t.since "
                     "WHERE r.record_id >= :lo GROUP BY r.user_id")
SQL_ACTIVE = ("SELECT ((timestamp_server - :launch) / :bin) AS b, count(DISTINCT user_id) AS n "
              "FROM record_entry WHERE record_id >= :lo AND timestamp_server >= :from GROUP BY 1")
SQL_SPOT = ("SELECT a.user_id, a.endpoint, a.timestamp_server, "
            "NULLIF(a.algo_state->>'request_index', '')::int AS request_index, "
            "a.algo_state->>'phase' AS phase, a.algo_state->>'draw' AS draw, "
            "NULLIF(a.algo_state->>'n_batches_served', '')::int AS n_batches_served, "
            "a.algo_state->'u_long' AS u_long, a.served_post_ids AS served_post_ids, "
            "a.signal_post_ids AS signal_post_ids, a.dwell_times AS dwell_times, "
            "NULLIF(a.algo_state->>'signal_batch', '')::int AS signal_batch, "
            "a.algo_state->'inventory'->>'file_sha256' AS inventory_sha256 "
            "FROM algo_exchange a WHERE a.user_id = ANY(:uids) ORDER BY a.user_id, a.timestamp_server, a.id")
ALL_SQL = [SQL_COLUMNS, SQL_ID_RANGE, SQL_ID_PROBE, SQL_EXCHANGES, SQL_RECORD_COUNTS, SQL_ACTIVE, SQL_SPOT]


def assert_select(sql):
    """Refuse anything that is not a single SELECT statement."""
    s = sql.strip().rstrip(";")
    if not s.upper().startswith("SELECT") or ";" in s:
        raise ValueError(f"only a single SELECT statement is allowed: {s[:60]}")


# ---- shared helpers --------------------------------------------------------------------------------
def import_reader(pfda_dir):
    """Return (SubsetReader class, package dir) from the clone at pfda_dir."""
    if pfda_dir not in sys.path:
        sys.path.insert(0, pfda_dir)
    import preferfeed_dataaccess as pfda
    from preferfeed_dataaccess import SubsetReader
    return SubsetReader, os.path.dirname(os.path.abspath(pfda.__file__))


def make_reader(SubsetReader, creds_path, creds_keys, countries, connect_timeout_s):
    """Return (reader, {country: error}) for countries whose key is missing in creds.yml."""
    # libpq reads this at connect time, so an unreachable server fails within the timeout.
    os.environ["PGCONNECT_TIMEOUT"] = str(connect_timeout_s)
    with open(creds_path) as fh:
        creds = yaml.safe_load(fh) or {}
    builder = SubsetReader(engines={})  # only used for its get_engine()
    engines, failures = {}, {}
    for cc in countries:
        key = creds_keys[cc]
        if key in creds:
            engines[cc] = builder.get_engine(creds[key])
        else:
            failures[cc] = f"no {key} in creds file"
    return SubsetReader(engines=engines, countries=list(engines)), failures


def errors_text(x):
    """The errors column as JSON text: None for a missing value, lists (also numpy arrays) dumped."""
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    if isinstance(x, str):
        return x
    return json.dumps(x.tolist() if hasattr(x, "tolist") else x)


def finish_visited(df, country):
    """Keep COLUMNS (optional ones filled with None when the schema has not got them), normalise
    errors to JSON text and condition to upper case, add country."""
    df = df.copy()
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise KeyError(f"visited_users has no column {missing}")
    for c in OPTIONAL_COLUMNS:
        if c not in df.columns:
            df[c] = None
    df = df[COLUMNS].copy()
    df["errors"] = df["errors"].apply(errors_text)
    df["condition"] = df["condition"].apply(
        lambda x: None if x is None or (isinstance(x, float) and pd.isna(x)) else str(getattr(x, "name", x)).upper())
    df["country"] = country
    return df


def read_visited(reader, country, start, end, tz):
    """visited_users rows of participants created in [start, end), with COLUMNS (see finish_visited)."""
    df = reader.get_table_subset(country, "visited_users", start=start, end=end, by="participant", tz=tz)
    return finish_visited(df, country)


def parse_json(x):
    """A JSON column as python: jsonb arrives decoded, text columns as str, missing as None."""
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    return json.loads(x) if isinstance(x, str) else x


# ---- live ------------------------------------------------------------------------------------------
class LiveSource:
    """The databases through the reader's engines."""

    def __init__(self, reader, timeout_s):
        self.reader, self.timeout_s = reader, timeout_s
        self._columns = {}

    def connection(self, cc):
        """A read-only transaction with the statement timeout; use as `with source.connection(cc) as con`."""
        from contextlib import contextmanager
        from sqlalchemy import text

        @contextmanager
        def cm():
            with self.reader.engines[cc].connect() as con:
                con.execute(text("SET TRANSACTION READ ONLY"))
                con.execute(text(f"SET LOCAL statement_timeout = {int(self.timeout_s) * 1000}"))
                try:
                    yield con
                finally:
                    con.rollback()
        return cm()

    def query(self, cc, sql, params=None, con=None):
        """Run one SELECT; pass con to reuse a connection (the bisection sends about 25 statements)."""
        assert_select(sql)
        from sqlalchemy import text
        if con is None:
            with self.connection(cc) as c:
                return self.query(cc, sql, params, c)
        res = con.execute(text(sql), params or {})
        rows = res.fetchall()
        return pd.DataFrame(rows, columns=list(res.keys()))

    def has_column(self, cc, table, column):
        if (cc, table) not in self._columns:
            self._columns[(cc, table)] = set(self.query(cc, SQL_COLUMNS, {"t": table})["column_name"])
        return column in self._columns[(cc, table)]

    def core(self, cc, start, end, tz):
        return read_visited(self.reader, cc, start, end, tz)

    def exchanges(self, cc, start_ms, end_ms):
        """Exchanges of participants created in [start_ms, end_ms): EXCHANGE_COLUMNS (+ attempt)."""
        att = ", a.attempt AS attempt" if self.has_column(cc, "algo_exchange", "attempt") else ""
        df = self.query(cc, SQL_EXCHANGES.format(attempt=att), {"start": int(start_ms), "end": int(end_ms)})
        df["country"] = cc
        return df

    def record_id_at(self, cc, t_ms):
        """Smallest record_id whose timestamp_server is >= t_ms, found by bisection on the primary key
        (None if the table is empty or has no such row)."""
        with self.connection(cc) as con:
            r = self.query(cc, SQL_ID_RANGE, None, con).iloc[0]
            if pd.isna(r["lo"]):
                return None
            lo, hi = int(r["lo"]), int(r["hi"])

            def at(m):
                d = self.query(cc, SQL_ID_PROBE, {"m": int(m)}, con)
                return None if d.empty else int(d.iloc[0]["t"])

            t_hi = at(hi)
            if t_hi is None or t_hi < t_ms:
                return None
            while lo < hi:
                mid = (lo + hi) // 2
                t = at(mid)
                if t is not None and t >= t_ms:
                    hi = mid
                else:
                    lo = mid + 1
            return lo

    def record_counts(self, cc, thresholds):
        """thresholds: DataFrame user_id, since_ms. Returns {user_id: record_entry rows with
        timestamp_server >= since_ms}. Scans record_entry from the record_id of the earliest threshold."""
        if thresholds.empty:
            return {}
        lo = self.record_id_at(cc, int(thresholds["since_ms"].min()) - 60_000)
        if lo is None:
            return {int(u): 0 for u in thresholds["user_id"]}
        df = self.query(cc, SQL_RECORD_COUNTS, {"uids": [int(u) for u in thresholds["user_id"]],
                                               "since": [int(t) for t in thresholds["since_ms"]], "lo": lo})
        got = {int(u): int(n) for u, n in zip(df["user_id"], df["n"])}
        return {int(u): got.get(int(u), 0) for u in thresholds["user_id"]}

    def active(self, cc, launch_ms, from_ms, bin_ms):
        """DataFrame bin_ms (bin start), n_active: distinct participants with a record row in the bin, for
        the bins that start at or after from_ms."""
        lo = self.record_id_at(cc, int(from_ms) - 60_000)
        if lo is None:
            return pd.DataFrame(columns=["bin_ms", "n_active"])
        df = self.query(cc, SQL_ACTIVE, {"launch": int(launch_ms), "bin": int(bin_ms), "lo": lo,
                                         "from": int(from_ms)})
        return pd.DataFrame({"bin_ms": int(launch_ms) + df["b"].astype("int64") * int(bin_ms),
                             "n_active": df["n"].astype("int64")})

    def spot(self, cc, uids):
        """Exchanges of the listed participants with u_long and served_post_ids (SPOT_COLUMNS)."""
        if not uids:
            return pd.DataFrame(columns=SPOT_COLUMNS)
        df = self.query(cc, SQL_SPOT, {"uids": [int(u) for u in uids]})
        df["u_long"] = df["u_long"].map(parse_json)
        df["served_post_ids"] = df["served_post_ids"].map(parse_json)
        df["signal_post_ids"] = df["signal_post_ids"].map(parse_json)
        df["dwell_times"] = df["dwell_times"].map(parse_json)
        return df


# ---- replay ----------------------------------------------------------------------------------------
class ExportSource:
    """The same questions answered from CC/window/table.parquet files under one folder."""

    def __init__(self, folder):
        self.folder = folder

    def _read(self, cc, table, columns=None):
        files = glob.glob(os.path.join(self.folder, cc, "*", f"{table}.parquet"))
        if len(files) != 1:
            raise FileNotFoundError(f"{cc} {table}: {len(files)} files under the export folder")
        return pd.read_parquet(files[0], columns=columns)

    def core(self, cc, start, end, tz):
        from aggregate import launch_ms
        df = self._read(cc, "visited_users")
        lo, hi = launch_ms(start, tz), pd.Timestamp(end).value // 1_000_000
        return finish_visited(df[(df["created_at"] >= lo) & (df["created_at"] < hi)], cc)

    def exchanges(self, cc, start_ms, end_ms):
        v = self._read(cc, "visited_users", ["id", "created_at"])
        ids = set(v.loc[(v["created_at"] >= start_ms) & (v["created_at"] < end_ms), "id"])
        ex = self._read(cc, "algo_exchange", ["user_id", "endpoint", "algo_type", "timestamp_server", "algo_state"])
        ex = ex[ex["user_id"].isin(ids)].copy()
        state = ex.pop("algo_state").map(lambda s: parse_json(s) or {})
        ex["request_index"] = pd.to_numeric(state.map(lambda d: d.get("request_index")), errors="coerce")
        ex["phase"] = state.map(lambda d: d.get("phase"))
        ex["country"] = cc
        return ex.reset_index(drop=True)

    def record_counts(self, cc, thresholds):
        rec = self._read(cc, "record_entry", ["user_id", "timestamp_server"])
        since = dict(zip(thresholds["user_id"], thresholds["since_ms"]))
        rec = rec[rec["user_id"].isin(since)]
        ok = rec["timestamp_server"] >= rec["user_id"].map(since)
        got = rec[ok].groupby("user_id").size().to_dict()
        return {int(u): int(got.get(u, 0)) for u in thresholds["user_id"]}

    def active(self, cc, launch_ms, from_ms, bin_ms):
        rec = self._read(cc, "record_entry", ["user_id", "timestamp_server"])
        rec = rec[rec["timestamp_server"] >= from_ms]
        b = int(launch_ms) + ((rec["timestamp_server"] - launch_ms) // bin_ms) * bin_ms
        g = rec.groupby(b)["user_id"].nunique()
        return pd.DataFrame({"bin_ms": g.index.astype("int64"), "n_active": g.values.astype("int64")})

    def spot(self, cc, uids):
        ex = self._read(cc, "algo_exchange")
        ex = ex[ex["user_id"].isin(set(uids))].sort_values(["user_id", "timestamp_server", "id"])
        state = ex["algo_state"].map(lambda s: parse_json(s) or {})
        return pd.DataFrame({
            "user_id": ex["user_id"].to_numpy(), "endpoint": ex["endpoint"].to_numpy(),
            "timestamp_server": ex["timestamp_server"].to_numpy(),
            "request_index": state.map(lambda d: d.get("request_index")).to_numpy(),
            "phase": state.map(lambda d: d.get("phase")).to_numpy(),
            "draw": state.map(lambda d: d.get("draw")).to_numpy(),
            "n_batches_served": state.map(lambda d: d.get("n_batches_served")).to_numpy(),
            "u_long": state.map(lambda d: d.get("u_long")).to_numpy(),
            "served_post_ids": ex["served_post_ids"].map(parse_json).to_numpy(),
            "signal_post_ids": (ex["signal_post_ids"].map(parse_json) if "signal_post_ids" in ex else pd.Series([None] * len(ex))).to_numpy(),
            "dwell_times": (ex["dwell_times"].map(parse_json) if "dwell_times" in ex else pd.Series([None] * len(ex))).to_numpy(),
            "signal_batch": state.map(lambda d: d.get("signal_batch")).to_numpy(),
            "inventory_sha256": state.map(lambda d: (d.get("inventory") or {}).get("file_sha256")).to_numpy()})

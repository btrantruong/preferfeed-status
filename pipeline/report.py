"""The local ids report (OUTDIR/ids_report.md, never published): short stays and restarts of a list of yougov ids.

Pure functions: tables in, markdown text out. A stay is the participant's total time on the feed, the sum of the
durations of all their attempts (init exchange to last record of each attempt; the gaps between attempts are not
counted). For every threshold in SHORT_STAY_S the report lists the ids that stayed shorter, how many of them
restarted, for which reason and how, and the median and maximum duration of the attempts that ended in a restart,
with the id of the longest.
"""
import numpy as np
import pandas as pd

STOP_CODES_DEFAULT = ("PAGE_RELOAD_DETECTED", "IDLE_DETECTED", "AUTOMATED_BROWSER_DETECTED")


def _label(r):
    return r["yougov_id"] if isinstance(r.get("yougov_id"), str) else f"db id {r['country']}:{int(r['user_id'])} (not in the list)"


def _fmt_s(minutes):
    return "-" if pd.isna(minutes) else f"{minutes * 60:.0f} s" if minutes < 2 else f"{minutes:.1f} min"


def restart_rows(att, parts, stop_codes):
    """One row per attempt that ended in a restart: duration, codes, whether a stop was logged, the gap to the next attempt."""
    a = att.sort_values(["country", "user_id", "attempt"]).copy()
    a["next_gap_min"] = a.groupby(["country", "user_id"])["gap_before_min"].shift(-1)
    r = a[a["ends_as"] == "restarted"].copy()
    r["logged_stop"] = r["codes"].map(lambda c: any(s in str(c).split(",") for s in stop_codes))
    return r


def short_stay_section(threshold_s, ids_df, att, stop_codes):
    """Markdown lines for one threshold. ids_df: one row per listed participant (country, user_id, yougov_id, total_min,
    n_attempts, status, condition)."""
    lines = [f"## Stayed less than {threshold_s} seconds", ""]
    short = ids_df[ids_df["total_min"].notna() & (ids_df["total_min"] * 60 < threshold_s)].sort_values("total_min")
    lines.append(f"{len(short)} of {len(ids_df)} listed participants with a recorded attempt.")
    lines.append("")
    if short.empty:
        return lines + ["No participant.", ""]
    lines += ["| yougov id | database id | condition | time on the feed | attempts | status |", "|---|---|---|---|---|---|"]
    for _, r in short.iterrows():
        lines.append(f"| {_label(r)} | {int(r['user_id'])} | {str(r['condition']).lower()} | {_fmt_s(r['total_min'])} | {int(r['n_attempts'])} | {r['status']} |")
    lines.append("")
    restarters = short[short["n_attempts"] >= 2]
    lines.append(f"Restarted (two or more attempts): {len(restarters)} of {len(short)}"
                 + (" (" + ", ".join(_label(r) for _, r in restarters.iterrows()) + ")." if len(restarters) else "."))
    lines.append("")
    keys = set(zip(restarters["country"], restarters["user_id"]))
    rr = restart_rows(att, None, stop_codes)
    rr = rr[[k in keys for k in zip(rr["country"], rr["user_id"])]]
    if rr.empty:
        return lines + ["No restart among them.", ""]
    lines += ["Reason, from the error codes logged during the attempt that ended in a restart (an attempt can carry several codes):", "",
              "| reason | restarts | participants |", "|---|---|---|"]
    reasons = {}
    for _, x in rr.iterrows():
        for c in (str(x["codes"]).split(",") if str(x["codes"]) not in ("", "nan") else ["no error logged"]):
            reasons.setdefault(c, []).append((x["country"], x["user_id"]))
    for c, v in sorted(reasons.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"| {c} | {len(v)} | {len(set(v))} |")
    n_stop = int(rr["logged_stop"].sum())
    gap = rr["next_gap_min"].dropna()
    lines += ["", f"How: {n_stop} of {len(rr)} restarts follow a logged stop (reload, idle or automated browser: the participant lands on an error page "
              f"that offers a restart link); {len(rr) - n_stop} follow no logged stop (the participant left and opened the study link again). "
              "The database does not show which link was used. "
              + (f"Time from the end of the attempt to the next start: median {_fmt_s(gap.median())}, maximum {_fmt_s(gap.max())}." if len(gap) else ""), ""]
    lines += restart_summary("Attempts that ended in a restart (these participants)", rr, ids_df)
    return lines


def restart_summary(title, rr, ids_df):
    out = [f"{title}: {len(rr)} attempts.", ""]
    if rr.empty:
        return out + [""]
    d = rr["duration_min"].dropna()
    top = rr.loc[d.idxmax()]
    who = ids_df[(ids_df["country"] == top["country"]) & (ids_df["user_id"] == top["user_id"])]
    label = _label(who.iloc[0]) if len(who) else f"db id {top['country']}:{int(top['user_id'])}"
    out += [f"- median duration {_fmt_s(d.median())}, maximum {_fmt_s(d.max())} (attempt {int(top['attempt'])} of {label})", ""]
    return out


def build_report(ids, ids_df, att, parts, pulled_iso, thresholds_s, stop_codes, reference):
    """The markdown text. ids: the listed yougov ids. ids_df: listed participants found (see short_stay_section)."""
    found = set(ids_df["yougov_id"]) if len(ids_df) else set()
    L = ["# Ids report: short stays and restarts (local, not published)", "",
         f"Pulled at {pulled_iso}. {len(ids)} ids listed, {len(found)} with a participant row in the pulled data"
         + (f"; no row for: {', '.join(i for i in ids if i not in found)}." if len(found) < len(ids) else "."), "",
         "A stay is the total time on the feed: the sum of the durations of all attempts, each from its init exchange to its last record; "
         "time between attempts is not counted. Reasons come from the error codes logged during an attempt.", ""]
    for t in sorted(thresholds_s, reverse=True):
        L += short_stay_section(t, ids_df, att, stop_codes)
    allr = restart_rows(att, parts, stop_codes)
    keys = set(zip(ids_df["country"], ids_df["user_id"]))
    mine = allr[[k in keys for k in zip(allr["country"], allr["user_id"])]]
    L += ["## Restarting attempts of all listed participants", ""] + restart_summary("Attempts that ended in a restart", mine, ids_df)
    L += ["## All participants in the pulled data (counts only)", ""]
    ok = parts[parts["total_min"].notna()]
    for t in sorted(thresholds_s, reverse=True):
        s = ok[ok["total_min"] * 60 < t]
        L.append(f"- stayed less than {t} s: {len(s)} of {len(ok)}; of these {int((s['n_attempts'] >= 2).sum())} restarted")
    d = allr["duration_min"].dropna()
    if len(d):
        L.append(f"- attempts that ended in a restart: {len(d)}, median {_fmt_s(d.median())}, maximum {_fmt_s(d.max())}")
    if reference:
        L += ["", f"Reference for in session or left: T_ref {reference['t_ref_min']:.1f} min ({reference['source']}, n {reference['n']})."]
    return "\n".join(L) + "\n"

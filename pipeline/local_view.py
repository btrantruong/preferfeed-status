"""Local view of the trajectories: one self-contained HTML file with every participant and every field. Never published.

  uv run --locked python local_view.py --live [--countries UK,DE] [--out FILE]
  uv run --locked python local_view.py --tables FOLDER --countries UK --alpha 0.7 --out FILE

--live    reads the databases (read-only SELECT): every participant created since the launch of its country who has at
          least one exchange, every condition, done or not, every attempt. No yougov id is read.
--tables  reads CC/window/{visited_users,algo_exchange}.parquet under FOLDER (a backup or an export).
The page opens without a server; it holds the shared panel modules (../js) and the data. It contains row-level data,
including the votes of the preference condition, so the output is refused inside this repository."""
import argparse
import base64
import json
import os
import posixpath
import re
import sys
from datetime import datetime, timezone

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import aggregate as A  # noqa: E402
import config as cfgmod  # noqa: E402
import db  # noqa: E402
import trajectory as T  # noqa: E402

ENTRY = "trajectory/local.js"
PREFIX = "traj:"
IMPORT = re.compile(r'((?:\bfrom|^\s*import)\s+)"(\.{1,2}/[^"]+)"', re.M)


def modules(js_dir, entry=ENTRY):
    """{name: source} of the entry module and everything it imports, relative imports renamed to PREFIX + name."""
    out, todo = {}, [entry]
    while todo:
        name = todo.pop()
        if name in out:
            continue
        with open(os.path.join(js_dir, name), encoding="utf-8") as fh:
            source = fh.read()

        def rename(m):
            target = posixpath.normpath(posixpath.join(posixpath.dirname(name), m.group(2)))
            todo.append(target)
            return f'{m.group(1)}"{PREFIX}{target}"'

        out[name] = IMPORT.sub(rename, source)
    return out


def embed_json(obj):
    """JSON that cannot close its script element: post texts are untrusted."""
    return json.dumps(obj, allow_nan=False, separators=(",", ":")).replace("<", "\\u003c")


def build_page(data, site_dir):
    with open(os.path.join(site_dir, "index.html"), encoding="utf-8") as fh:
        style = re.search(r"<style>(.*?)</style>", fh.read(), re.S).group(1)
    imports = {PREFIX + n: "data:text/javascript;base64," + base64.b64encode(s.encode()).decode()
               for n, s in modules(os.path.join(site_dir, "js")).items()}
    title = data["meta"]["title"]
    esc = title.replace("&", "&amp;").replace("<", "&lt;")
    return ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>{esc}</title>\n<style>{style}</style>\n</head>\n<body>\n<main>\n"
            f'<header><div class="title-row"><h1>{esc}</h1></div><p class="sub">{data["meta"]["subtitle"]}</p></header>\n'
            '<div id="app"></div>\n</main>\n'
            f'<script type="application/json" id="data">{embed_json(data)}</script>\n'
            f'<script type="importmap">{json.dumps({"imports": imports})}</script>\n'
            f'<script type="module">import "{PREFIX}{ENTRY}";</script>\n</body>\n</html>\n')


def flag(x):
    """A boolean column that may arrive as bool, number or text."""
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return False
    return str(x).strip().lower() in ("true", "t", "1", "1.0")


def collect(source, countries, since_ms, inventories, params, chunk):
    """Trajectories of every participant with exchanges. Returns (users, posts, summary)."""
    users, posts = [], {}
    summary = {"older_algorithm": 0, "no_exchange": 0, "checks": {}}
    for cc in countries:
        people = source.view_users(cc, since_ms[cc])
        ids = [int(u) for u in people["user_id"]]
        frames = [source.spot(cc, ids[k:k + chunk]) for k in range(0, len(ids), chunk)]
        frames = [f for f in frames if not f.empty]
        rows = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=db.SPOT_COLUMNS)
        by_user = {int(u): g for u, g in rows.groupby("user_id", sort=False)}
        for person in people.itertuples():
            g = by_user.get(int(person.user_id))
            if g is None:
                summary["no_exchange"] += 1
                continue
            if g["n_batches_served"].isna().any():     # an older algorithm: no batch numbers, no signal batch
                summary["older_algorithm"] += 1
                continue
            condition = str(getattr(person.condition, "name", person.condition)).upper()
            attempts = [T.build_attempt(part, inventories[cc], params, posts) for part in T.split_attempts(g)]
            total = summary["checks"].setdefault(f"{cc} {condition}", {"u_short": [0, 0], "u_long": [0, 0]})
            for a in attempts:
                for key, (ok, n) in a["checks"].items():
                    total[key][0] += ok
                    total[key][1] += n
            users.append({"country": cc, "user_id": int(person.user_id), "condition": condition, "done": flag(person.done),
                          "cancelled": flag(person.cancelled), "created_at": int(person.created_at), "attempts": attempts})
    users.sort(key=lambda u: (u["country"], u["user_id"]))
    return users, posts, summary


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--live", action="store_true")
    src.add_argument("--tables", help="folder with CC/window/table.parquet files")
    p.add_argument("--countries", help="comma separated; default all of COUNTRIES")
    p.add_argument("--since", help="only participants created from this time (ISO, read in TZ); live default: the launch")
    p.add_argument("--alpha", type=float, help="alpha of the data; default ALGO_ALPHA")
    p.add_argument("--inventory", help="inventory parquet; default INVENTORY_FILE")
    p.add_argument("--out", help="output file; default OUTDIR/trajectories.html")
    p.add_argument("--chunk", type=int, default=100, help="participants per exchange query")
    p.add_argument("--title", help="page title")
    args = p.parse_args(argv)

    cfg = cfgmod.load(HERE)
    countries = [c.upper() for c in cfgmod.parse_list(args.countries)] if args.countries else cfg.countries
    inventory = os.path.abspath(args.inventory or cfg.inventory_file)
    if not os.path.isfile(inventory):
        p.error("no inventory file: pass --inventory or set INVENTORY_FILE")
    out = os.path.abspath(args.out or os.path.join(cfg.outdir, "trajectories.html"))
    if cfgmod.is_inside(out, cfg.site_dir):
        p.error(f"--out {out} is inside the public repository {cfg.site_dir}")
    params = {**cfg.params, **({"algo_alpha": args.alpha} if args.alpha is not None else {})}

    if args.live:
        reader_cls, _ = db.import_reader(cfg.pfda_dir)
        reader, failures = db.make_reader(reader_cls, cfg.creds, cfg.creds_keys, countries, cfg.connect_timeout_s)
        source = db.LiveSource(reader, params["detail_timeout_s"])
        since = {c: A.launch_ms(args.since or cfg.launch_of(c), cfg.tz) for c in countries}
    else:
        source, failures = db.ExportSource(os.path.abspath(args.tables)), {}
        since = {c: A.launch_ms(args.since, cfg.tz) if args.since else 0 for c in countries}

    inventories = T.prepare_inventory(pd.read_parquet(inventory, columns=T.INVENTORY_COLUMNS))
    users, posts, summary, failed = [], {}, {"older_algorithm": 0, "no_exchange": 0, "checks": {}}, dict(failures)
    for cc in countries:
        if cc in failed:
            continue
        try:
            u, found, s = collect(source, [cc], since, inventories, params, args.chunk)
        except Exception as e:  # one server down must not stop the others
            failed[cc] = f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"
            continue
        users += u
        posts.update(found)
        summary["older_algorithm"] += s["older_algorithm"]
        summary["no_exchange"] += s["no_exchange"]
        summary["checks"].update(s["checks"])
    if not users:
        sys.exit(f"no participant to show; failed: {failed}")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    title = args.title or ("preferFeed trajectories, live launch" if args.live else "preferFeed trajectories")
    subtitle = (f"{len(users)} participants ({', '.join(sorted({u['country'] for u in users}))}); alpha {params['algo_alpha']:g}; "
                f"{'database read' if args.live else 'tables read, page built'} {now}. Local file with row-level data: do not share."
                + (f" Failed: {', '.join(failed)}." if failed else ""))
    data = {"meta": {"title": title, "subtitle": subtitle, "alpha": params["algo_alpha"], "built": now,
                     "dwell_cap_s": params["spot_dwell_cap_s"]}, "users": users, "posts": posts}
    os.makedirs(os.path.dirname(out), exist_ok=True)
    A.write_atomic(out, build_page(data, cfg.site_dir))

    print(f"{len(users)} participants, {sum(len(u['attempts']) for u in users)} attempts, {len(posts)} posts")
    print(f"left out: {summary['older_algorithm']} on an older algorithm, {summary['no_exchange']} without an exchange")
    if failed:
        print("failed:", failed)
    print("checks against the log (matching of checked requests)")
    for key, c in sorted(summary["checks"].items()):
        print(f"  {key:16s} u_short {c['u_short'][0]} of {c['u_short'][1]}   u_long {c['u_long'][0]} of {c['u_long'][1]}")
    print(f"written {out} ({os.path.getsize(out) / 1e6:.1f} MB)")
    return summary


if __name__ == "__main__":
    main()

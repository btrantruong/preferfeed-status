"""Serve the page locally with /data/ mapped to OUTDIR (the last run's files, pushed or not).

  ./run.sh is not needed; run:  uv run --locked python preview.py [--port 8765] [--host 127.0.0.1]
Then open http://127.0.0.1:8765/ (on barnard through VS Code port forwarding).
"""
import argparse
import functools
import http.server
import os
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config as cfgmod  # noqa: E402

PUBLIC = {"index.html", "app.js", ""}  # site files served from the clone


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, site_dir, data_dir, **kw):
        self.site_dir, self.data_dir = site_dir, data_dir
        super().__init__(*a, directory=site_dir, **kw)

    def translate_path(self, path):
        rel = urllib.parse.unquote(urllib.parse.urlsplit(path).path).lstrip("/")
        if rel.startswith("data/"):
            name = os.path.basename(rel)
            if name in ("status_bins.csv", "meta.json"):  # never serve participants.csv
                return os.path.join(self.data_dir, name)
            return os.path.join(self.data_dir, "__missing__")
        if rel not in PUBLIC:
            return os.path.join(self.site_dir, "__missing__")
        return os.path.join(self.site_dir, rel or "index.html")

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--data-dir", help="folder with status_bins.csv and meta.json (default OUTDIR)")
    args = p.parse_args()
    cfg = cfgmod.load(HERE)
    data_dir = args.data_dir or cfg.outdir
    handler = functools.partial(Handler, site_dir=cfg.site_dir, data_dir=data_dir)
    with http.server.ThreadingHTTPServer((args.host, args.port), handler) as srv:
        print(f"serving {cfg.site_dir} with data from {data_dir} at http://{args.host}:{args.port}/")
        srv.serve_forever()


if __name__ == "__main__":
    main()

# pipeline

Pulls `visited_users` from each country database, gives each participant one status (see `../README.md`), counts them in time bins and publishes `../data/status_bins.csv` and `../data/meta.json`. Every machine that runs it uses the same code and the same `config.env`; only `config.local.env` differs.

## Files

| file | role |
|---|---|
| `config.env` | run parameters shared by all machines (launch, timezone, bins, codes, thresholds) |
| `config.local.env.example` | template for `config.local.env` (git-ignored): machine label, path to the `preferfeed_dataaccess` clone, creds file, output folder, uv |
| `run.sh` | the command to run; starts `run.py` in the locked uv env |
| `run.py` | lock, `git pull --ff-only`, aggregate, summary, publish |
| `db.py` | reads `visited_users` through `SubsetReader` from `preferfeed_dataaccess` (imported from `PFDA_DIR`) |
| `classify.py` | status and reason per participant (pure functions) |
| `aggregate.py` | bins, `meta.json`, carry-over for failed servers, history |
| `publish.py` | copies the two data files into `../data/`, commits only them, pushes |
| `preview.py` | serves the page locally with `/data/` mapped to `OUTDIR` |
| `tests/` | synthetic tests (no study data) |

## Set up a machine (once)

Needs uv, git push access to this repo, a clone of `preferfeed_dataaccess` with its creds file, and network access to the databases.

```sh
cd pipeline
cp config.local.env.example config.local.env   # then edit the paths
uv sync --locked
uv run --locked pytest -q tests
```

`OUTDIR` and `CREDS` must be outside this repo; `run.py` refuses to start otherwise.

## Run

```sh
./run.sh --no-push                         # pull and look at the summary
./run.sh                                   # pull and publish
./run.sh --no-push --set LAUNCH=2026-11-20T14:00   # override a config value for one run
uv run --locked python preview.py          # page with the last OUTDIR data at http://127.0.0.1:8765/
```

Each run starts with `git pull --ff-only`, so a machine always continues from the last published data. If no server answers, nothing is written or published. A server that fails keeps its last published counts, marked with their time on the page. `OUTDIR` keeps `participants.csv` (one row per participant, never published), `history/status_bins_history.csv` (every run's bins) and `run.log`.

## Switching machines

Run on one machine at a time. To switch, run `./run.sh` on the other machine: its first step pulls the latest data commit, and its push is then a fast-forward. If both push at once, the second push is rejected; run again on the machine you keep. Counts do not depend on the machine, since each run recomputes everything since the launch.

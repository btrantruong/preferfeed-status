# pipeline

Changelog
- 2026-11-24: added the registry of published files (cubes.py), the detail pull (detail.py), integrity flags and attempts (checks.py), the spot check (spot.py), the replay source and the new config keys.

Pulls `visited_users` from each country database, gives each participant one status (see `../README.md`), builds the aggregate files listed in `cubes.py` (see the table in `../README.md`) and publishes them with `../data/meta.json`. A second, separate pull (detail) reads `algo_exchange` and `record_entry`. Every machine that runs it uses the same code and the same `config.env`; only `config.local.env` differs.

## Files

| file | role |
|---|---|
| `config.env` | run parameters shared by all machines (launch, timezone, bins, codes, thresholds) |
| `config.local.env.example` | template for `config.local.env` (git-ignored): machine label, path to the `preferfeed_dataaccess` clone, creds file, output folder, uv |
| `run.sh` | the command to run; starts `run.py` in the locked uv env |
| `run.py` | lock, `git pull --ff-only`, aggregate, summary, publish |
| `db.py` | reads through `SubsetReader` from `preferfeed_dataaccess` (imported from `PFDA_DIR`): the core pull, the detail queries (read-only SELECT with a statement timeout) and the replay source that reads an export folder |
| `checks.py` | attempts, retakes and integrity flags (pure functions) |
| `cubes.py` | one builder per published file and the registry of files, columns and window kinds |
| `detail.py` | the detail pull per country, with the cache of final counts (`detail_cache.json` in `OUTDIR`) |
| `spot.py` | participant list, default picks, batches and post vectors of the local-only spot check |
| `classify.py` | status and reason per participant (pure functions) |
| `aggregate.py` | runs the registry, carry-over for failed servers and failed detail pulls, `meta.json`, history |
| `publish.py` | copies the produced registry files and `meta.json` into `../data/`, commits only them, pushes |
| `preview.py` | serves the page locally with `/data/` mapped to the registry files of `OUTDIR`, and `/local/spot_users.json` (panel D) from `OUTDIR` |
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

Each run starts with `git pull --ff-only`, so a machine always continues from the last published data. If no server answers, nothing is written or published. A server that fails keeps its last published counts, marked with their time on the page. `OUTDIR` keeps `participants.csv` (one row per participant, never published), `history/status_bins_history.csv` (every run's bins), `detail_cache.json`, `spot_users.json` (never published) and `run.log`.

## Switching machines

Run on one machine at a time. To switch, run `./run.sh` on the other machine: its first step pulls the latest data commit, and its push is then a fast-forward. If both push at once, the second push is rejected; run again on the machine you keep. Counts do not depend on the machine, since each run recomputes everything since the launch.

## Detail pull and parameters

`DETAIL` in `config.env` is `off` (default: core files only), `basic` (record counts of done participants, algorithm exchanges, spot check) or `full` (adds the active participants per bin). Every detail statement is a read-only SELECT with a statement timeout (`DETAIL_TIMEOUT_S`); a country whose detail pull fails or times out keeps its last published detail rows, marked with their time in `meta.json`, and the core files are still published. `record_entry` has only its primary key as an index, so its queries are bounded by `record_id` (lower bound found by bisection on `timestamp_server`), counts of done participants are cached once final, and active participants are cached per finished bin. All other keys (bin widths, thresholds, histogram ranges, flow steps, spot check) are listed with comments in `config.env`; `config.py` checks that `EVENT_BIN_MINUTES` divides `BIN_MINUTES`, that `FLAG_BIN_MINUTES` is a multiple of it, and the other ranges.

The spot check needs `INVENTORY_FILE` in `config.local.env` (the runtime inventory parquet) and writes `OUTDIR/spot_users.json`, which holds one participant's profile and the posts they saw: `publish.py` never copies it, `preview.py` serves it under `/local/` only.

## Replay

`./run.sh --no-push --no-pull --set SOURCE=export:FOLDER --set PULLED_AT=2026-11-21T00:00:00Z --set LAUNCH=2026-11-20T01:00 --set OUTDIR=/some/scratch/folder --set DETAIL=full` writes every file from an export (`FOLDER/CC/window/table.parquet`) without a database. Use `python preview.py --data-dir <that OUTDIR>` to look at the page.

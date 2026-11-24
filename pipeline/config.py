"""Load the run configuration: config.env (shared), config.local.env (per machine), --set overrides."""
import os
from dataclasses import dataclass

SHARED_FILE = "config.env"
LOCAL_FILE = "config.local.env"

SHARED_KEYS = ["LAUNCH", "TZ", "COUNTRIES", "CREDS_KEYS", "BIN_MINUTES", "SESSION_MIN",
               "IGNORE_CODES", "STOP_CODES", "IDLE_MIN_SECONDS", "IDLE_MIN_POSTS",
               "STALE_AFTER_MIN", "REFRESH_MIN", "CONNECT_TIMEOUT_S", "MIN_PUSH_GAP_MIN",
               "SCRIPTS_URL", "GIT_REMOTE", "GIT_BRANCH"]
LOCAL_KEYS = ["MACHINE", "PFDA_DIR", "CREDS", "OUTDIR"]


@dataclass(frozen=True)
class Config:
    launch: str
    tz: str
    countries: list
    creds_keys: dict
    bin_minutes: int
    session_min: int
    ignore_codes: list
    stop_codes: dict          # label -> code, e.g. {"idle": "IDLE_DETECTED"}
    idle_min_seconds: int
    idle_min_posts: int
    stale_after_min: object   # int or None
    refresh_min: float
    connect_timeout_s: int
    min_push_gap_min: float
    scripts_url: str
    git_remote: str
    git_branch: str
    machine: str
    pfda_dir: str
    creds: str
    outdir: str
    site_dir: str             # the preferfeed-status clone (parent of pipeline/)


def read_env_file(path):
    """Parse KEY=VALUE lines; blank lines and # comments are skipped, surrounding quotes stripped."""
    out = {}
    with open(path) as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ValueError(f"{path}:{n}: expected KEY=VALUE, got {line!r}")
            key, value = line.split("=", 1)
            out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def parse_list(value):
    return [v.strip() for v in value.split(",") if v.strip()]


def parse_map(value):
    """'a:b,c:d' -> {'a': 'b', 'c': 'd'}"""
    out = {}
    for item in parse_list(value):
        if ":" not in item:
            raise ValueError(f"expected label:value, got {item!r}")
        k, v = item.split(":", 1)
        out[k.strip()] = v.strip()
    return out


def parse_overrides(items):
    out = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"--set expects KEY=VALUE, got {item!r}")
        k, v = item.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def is_inside(path, parent):
    path, parent = os.path.realpath(path), os.path.realpath(parent)
    return os.path.commonpath([path, parent]) == parent


def load(pipeline_dir, overrides=None):
    """Return a validated Config. overrides: list of 'KEY=VALUE' strings (from --set)."""
    shared_path = os.path.join(pipeline_dir, SHARED_FILE)
    local_path = os.path.join(pipeline_dir, LOCAL_FILE)
    if not os.path.isfile(local_path):
        raise FileNotFoundError(f"missing {local_path}; copy {LOCAL_FILE}.example and fill it in")
    raw = read_env_file(shared_path)
    raw.update(read_env_file(local_path))
    over = parse_overrides(overrides)
    unknown = set(over) - set(SHARED_KEYS) - set(LOCAL_KEYS) - {"UV"}
    if unknown:
        raise ValueError(f"unknown --set keys: {sorted(unknown)}")
    raw.update(over)
    missing = [k for k in SHARED_KEYS + LOCAL_KEYS if k not in raw]
    if missing:
        raise ValueError(f"missing config keys: {missing}")

    site_dir = os.path.realpath(os.path.join(pipeline_dir, ".."))
    expand = lambda p: os.path.abspath(os.path.expanduser(p))
    cfg = Config(
        launch=raw["LAUNCH"],
        tz=raw["TZ"],
        countries=[c.upper() for c in parse_list(raw["COUNTRIES"])],
        creds_keys={k.upper(): v for k, v in parse_map(raw["CREDS_KEYS"]).items()},
        bin_minutes=int(raw["BIN_MINUTES"]),
        session_min=int(raw["SESSION_MIN"]),
        ignore_codes=parse_list(raw["IGNORE_CODES"]),
        stop_codes=parse_map(raw["STOP_CODES"]),
        idle_min_seconds=int(raw["IDLE_MIN_SECONDS"]),
        idle_min_posts=int(raw["IDLE_MIN_POSTS"]),
        stale_after_min=int(raw["STALE_AFTER_MIN"]) if raw["STALE_AFTER_MIN"] else None,
        refresh_min=float(raw["REFRESH_MIN"]),
        connect_timeout_s=int(raw["CONNECT_TIMEOUT_S"]),
        min_push_gap_min=float(raw["MIN_PUSH_GAP_MIN"]),
        scripts_url=raw["SCRIPTS_URL"],
        git_remote=raw["GIT_REMOTE"],
        git_branch=raw["GIT_BRANCH"],
        machine=raw["MACHINE"],
        pfda_dir=expand(raw["PFDA_DIR"]),
        creds=expand(raw["CREDS"]),
        outdir=expand(raw["OUTDIR"]),
        site_dir=site_dir,
    )
    validate(cfg)
    return cfg


def validate(cfg):
    if cfg.bin_minutes <= 0 or cfg.session_min < 0:
        raise ValueError("BIN_MINUTES must be > 0 and SESSION_MIN >= 0")
    if "other" in cfg.stop_codes:
        raise ValueError("STOP_CODES label 'other' is reserved")
    missing_keys = [c for c in cfg.countries if c not in cfg.creds_keys]
    if missing_keys:
        raise ValueError(f"CREDS_KEYS has no entry for {missing_keys}")
    # Row-level files must never land in the public repo.
    if is_inside(cfg.outdir, cfg.site_dir):
        raise ValueError(f"OUTDIR {cfg.outdir} is inside the site repo {cfg.site_dir}")
    if is_inside(cfg.creds, cfg.site_dir):
        raise ValueError(f"CREDS {cfg.creds} is inside the site repo {cfg.site_dir}")
    if not os.path.isdir(os.path.join(cfg.pfda_dir, "preferfeed_dataaccess")):
        raise FileNotFoundError(f"PFDA_DIR {cfg.pfda_dir} has no preferfeed_dataaccess package")

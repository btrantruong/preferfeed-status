"""Load the run configuration: config.env (shared), config.local.env (per machine), --set overrides."""
import os
from dataclasses import dataclass, field

SHARED_FILE = "config.env"
LOCAL_FILE = "config.local.env"

SHARED_KEYS = ["LAUNCH", "TZ", "COUNTRIES", "CREDS_KEYS", "BIN_MINUTES", "SESSION_MIN",
               "IGNORE_CODES", "STOP_CODES", "IDLE_MIN_SECONDS", "IDLE_MIN_POSTS",
               "STALE_AFTER_MIN", "REFRESH_MIN", "CONNECT_TIMEOUT_S", "MIN_PUSH_GAP_MIN",
               "SCRIPTS_URL", "GIT_REMOTE", "GIT_BRANCH"]
LOCAL_KEYS = ["MACHINE", "PFDA_DIR", "CREDS", "OUTDIR"]
# Optional per-machine keys (default in the second column; empty string = not set).
OPTIONAL_LOCAL_KEYS = {"INVENTORY_FILE": "", "SOURCE": "live", "PULLED_AT": ""}
# Optional shared keys (config.env or --set). PULL_COUNTRIES: the countries queried in this run (a subset of
# COUNTRIES; empty = all). LAUNCH_BY_COUNTRY: label:time pairs for countries that launch later than LAUNCH.
OPTIONAL_SHARED_KEYS = {"PULL_COUNTRIES": "", "LAUNCH_BY_COUNTRY": ""}

# Chart and detail-pull parameters: key -> (kind, default). config.env may set any of them; a key that is
# missing there takes the default, so an older config.env keeps working. They are copied to meta.json
# ("params") so that the page holds no constants.
PARAM_SPEC = {
    "EVENT_BIN_MINUTES": ("int", 5),        # bins of the event charts; must divide BIN_MINUTES
    "FLAG_BIN_MINUTES": ("int", 60),        # bins of dc1; a multiple of BIN_MINUTES
    "MIN_N_RATE": ("int", 5),               # dc1: hours with fewer done participants are drawn faded
    "RECORDS_BIN_WIDTH": ("int", 2000),     # dc2
    "RECORDS_MAX": ("int", 50000),          # dc2: open last bin; a multiple of RECORDS_BIN_WIDTH
    "REQUESTS_MAX": ("int", 40),            # dc3: open last bin
    "BATCH_SIZE": ("int", 5),               # posts per batch (timeline config)
    "DIFF_RANGE": ("int", 10),              # dc3: requests minus viewed_posts / BATCH_SIZE, open ends at +-
    "ATTEMPTS_MAX": ("int", 4),             # cs2: this many starts and more share one bin
    "ATTEMPT_MARGIN_S": ("int", 10),        # records of the final attempt start this long before its init
    "ERROR_AGE_BIN_MIN": ("int", 1),        # se3
    "ERROR_AGE_MAX_MIN": ("int", 20),       # se3: open last bin; a multiple of ERROR_AGE_BIN_MIN
    "SERVER_ERROR_CODE": ("str", "SERVER_ERROR"),
    "CLIENT_ERROR_CODES": ("list", "CLIENT_TRACKING_SEND_FAILED,CLIENT_FEED_INIT_FAILED,CLIENT_FEED_BATCH_LOAD_FAILED"),
    "FLOW_STEPS": ("int", 4),               # se2: first k error runs per participant
    "FLOW_EXCLUDE_CODES": ("list", ""),     # se2: codes left out of the flow (empty: every code is shown)
    "WARMUP_MAX_INDEX": ("int", 10),        # ap2
    "SPOT_MAX_USERS": ("int", 30),          # sp1, sp2: most recent done participants per country in the list
    "SPOT_MIN_REQUESTS": ("int", 10),       # sp1, sp2: default pick needs this many next_batch exchanges
    "SPOT_USER": ("str", ""),               # COUNTRY:ID, overrides the default pick of the PREFERENCE condition
    "SPOT_TEXT_MAX_CHARS": ("int", 2000),   # sp2: longer post texts are cut and marked
    "SPOT_PUBLISH": ("str", "on"),          # on: spot_users.json (panel D) is published with the data; off: it is not, and a published copy is removed
    "SPOT_DWELL_CAP_S": ("int", 30),        # sp2: dwell time (seconds) at which the point size stops growing
    "DETAIL_TIMEOUT_S": ("int", 60),        # statement timeout of every detail query
    "DETAIL": ("str", "off"),               # off, basic (Q1, Q2, Q4) or full (adds Q3)
    "MAX_FILE_KB": ("int", 500),            # warning only
}
# parameters the page needs (meta.json "params"); the others only steer the pipeline
PAGE_PARAMS = ["EVENT_BIN_MINUTES", "FLAG_BIN_MINUTES", "MIN_N_RATE", "RECORDS_BIN_WIDTH", "RECORDS_MAX",
               "REQUESTS_MAX", "BATCH_SIZE", "DIFF_RANGE", "ATTEMPTS_MAX", "ERROR_AGE_BIN_MIN",
               "ERROR_AGE_MAX_MIN", "SERVER_ERROR_CODE", "CLIENT_ERROR_CODES", "FLOW_STEPS",
               "WARMUP_MAX_INDEX", "SPOT_MAX_USERS", "SPOT_DWELL_CAP_S"]
DETAIL_MODES = ["off", "basic", "full"]


def parse_param(kind, value):
    if kind == "int":
        return int(value)
    if kind == "list":
        return parse_list(value)
    return str(value)


def default_params():
    """PARAM_SPEC defaults, parsed (what config.env gives when it sets none of them)."""
    return {k.lower(): parse_param(kind, default) for k, (kind, default) in PARAM_SPEC.items()}


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
    params: dict = field(default_factory=default_params)   # PARAM_SPEC keys in lower case, parsed
    inventory_file: str = ""  # runtime inventory parquet for the spot check (local only)
    source: str = "live"      # live or export:FOLDER (replay)
    pulled_at: str = ""       # ISO time of the pull, replay only
    pull_countries: list = field(default_factory=list)       # queried in this run; empty = every country
    launch_by_country: dict = field(default_factory=dict)    # country -> naive launch time (in tz) if later than launch

    def pulled_countries(self):
        """Countries queried in this run, in the order of `countries`."""
        return [c for c in self.countries if not self.pull_countries or c in self.pull_countries]

    def launch_of(self, cc):
        """Launch time of one country (naive, in tz): its own entry or the shared LAUNCH."""
        return self.launch_by_country.get(cc, self.launch)


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
    unknown = set(over) - set(SHARED_KEYS) - set(LOCAL_KEYS) - set(PARAM_SPEC) - set(OPTIONAL_LOCAL_KEYS) - set(OPTIONAL_SHARED_KEYS) - {"UV"}
    if unknown:
        raise ValueError(f"unknown --set keys: {sorted(unknown)}")
    raw.update(over)
    missing = [k for k in SHARED_KEYS + LOCAL_KEYS if k not in raw]
    if missing:
        raise ValueError(f"missing config keys: {missing}")

    params = {k.lower(): parse_param(kind, raw.get(k, default)) for k, (kind, default) in PARAM_SPEC.items()}
    optional = {k: raw.get(k, d) for k, d in {**OPTIONAL_LOCAL_KEYS, **OPTIONAL_SHARED_KEYS}.items()}
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
        params=params,
        inventory_file=expand(optional["INVENTORY_FILE"]) if optional["INVENTORY_FILE"] else "",
        source=optional["SOURCE"],
        pulled_at=optional["PULLED_AT"],
        pull_countries=[c.upper() for c in parse_list(optional["PULL_COUNTRIES"])],
        launch_by_country={k.upper(): v for k, v in parse_map(optional["LAUNCH_BY_COUNTRY"]).items()},
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
    bad = [c for c in cfg.pull_countries if c not in cfg.countries]
    if bad:
        raise ValueError(f"PULL_COUNTRIES has {bad}, which are not in COUNTRIES {cfg.countries}")
    bad = [c for c in cfg.launch_by_country if c not in cfg.countries]
    if bad:
        raise ValueError(f"LAUNCH_BY_COUNTRY has {bad}, which are not in COUNTRIES {cfg.countries}")
    import pandas as pd
    first = pd.Timestamp(cfg.launch)
    for cc, t in cfg.launch_by_country.items():
        if pd.Timestamp(t) < first:
            raise ValueError(f"LAUNCH_BY_COUNTRY {cc} {t} is before LAUNCH {cfg.launch}; LAUNCH is the earliest launch")
    # Row-level files must never land in the public repo.
    if is_inside(cfg.outdir, cfg.site_dir):
        raise ValueError(f"OUTDIR {cfg.outdir} is inside the site repo {cfg.site_dir}")
    if is_inside(cfg.creds, cfg.site_dir):
        raise ValueError(f"CREDS {cfg.creds} is inside the site repo {cfg.site_dir}")
    validate_params(cfg)
    if cfg.source == "live" and not os.path.isdir(os.path.join(cfg.pfda_dir, "preferfeed_dataaccess")):
        raise FileNotFoundError(f"PFDA_DIR {cfg.pfda_dir} has no preferfeed_dataaccess package")


def validate_params(cfg):
    """Divisibility and range rules of the chart parameters."""
    p = cfg.params
    for key in ("event_bin_minutes", "flag_bin_minutes", "records_bin_width", "records_max", "requests_max",
                "batch_size", "diff_range", "attempts_max", "error_age_bin_min", "error_age_max_min",
                "flow_steps", "warmup_max_index", "spot_max_users", "detail_timeout_s", "spot_dwell_cap_s"):
        if p[key] <= 0:
            raise ValueError(f"{key.upper()} must be > 0")
    if cfg.bin_minutes % p["event_bin_minutes"]:
        raise ValueError(f"EVENT_BIN_MINUTES ({p['event_bin_minutes']}) must divide BIN_MINUTES ({cfg.bin_minutes})")
    if p["flag_bin_minutes"] % cfg.bin_minutes:
        raise ValueError(f"FLAG_BIN_MINUTES ({p['flag_bin_minutes']}) must be a multiple of BIN_MINUTES")
    if p["records_max"] % p["records_bin_width"]:
        raise ValueError("RECORDS_MAX must be a multiple of RECORDS_BIN_WIDTH")
    if p["error_age_max_min"] % p["error_age_bin_min"]:
        raise ValueError("ERROR_AGE_MAX_MIN must be a multiple of ERROR_AGE_BIN_MIN")
    if p["detail"] not in DETAIL_MODES:
        raise ValueError(f"DETAIL must be one of {DETAIL_MODES}")
    if p["spot_publish"] not in ("on", "off"):
        raise ValueError("SPOT_PUBLISH must be on or off")
    if p["spot_user"] and (":" not in p["spot_user"] or not p["spot_user"].split(":", 1)[1].isdigit()):
        raise ValueError("SPOT_USER must be COUNTRY:ID")
    if cfg.source != "live":
        if not cfg.source.startswith("export:") or not cfg.source[len("export:"):]:
            raise ValueError("SOURCE must be live or export:FOLDER")
        if not cfg.pulled_at:
            raise ValueError("SOURCE=export:... needs PULLED_AT (ISO time of the replayed pull)")

"""Read visited_users through the preferfeed_dataaccess reader (SubsetReader).

The package is imported from PFDA_DIR (config.local.env), since its path differs by machine.
Engines are built from creds.yml with CREDS_KEYS (country -> key), so no aliased temp creds file
is written.
"""
import json
import os
import sys

import yaml

COLUMNS = ["id", "created_at", "done", "cancelled", "errors"]


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


def read_visited(reader, country, start, end, tz):
    """visited_users rows of participants created in [start, end), with COLUMNS only.
    errors is normalised to JSON text (it may come back as a list from a json column)."""
    df = reader.get_table_subset(country, "visited_users", start=start, end=end,
                                 by="participant", tz=tz)
    df = df[COLUMNS].copy()
    df["errors"] = df["errors"].apply(
        lambda x: x if x is None or isinstance(x, str) else json.dumps(x))
    df["country"] = country
    return df

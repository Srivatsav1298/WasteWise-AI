"""Compare two sets of published artefacts and report the ones that drifted.

The pipeline promises that two clean runs publish the same numbers. The
artefacts still carry the identity of the run and the wall clock, so those
parts are ignored: the run id, the timestamps, the paths that embed the run
id, the observed values and the age inside a freshness message. Everything
else has to be identical, or the pipeline is not reproducible.

    python scripts/check_reproducible.py /tmp/first_run data/marts
"""
import argparse
import json
import re
import sys
from pathlib import Path

VOLATILE = {
    "generated_at",
    "started_at",
    "ingested_at",
    "run_id",
    "timestamp",
    "_ingested_at",
    "created_at",
    "bronze_snapshot",
    "silver_path",
    "clean_path",
    "observed",
}


def strip(value):
    """Drop the parts that move with the clock, keep the rest."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in VOLATILE:
                continue
            if key == "message" and isinstance(item, str):
                # A freshness or recency message states an age in days, so the
                # digits move with the clock. The words around them must not.
                out[key] = re.sub(r"\d+(?:\.\d+)?", "#", item)
                continue
            out[key] = strip(item)
        return out
    if isinstance(value, list):
        return [strip(item) for item in value]
    return value


def same_artefact(first_text, second_text):
    try:
        return strip(json.loads(first_text)) == strip(json.loads(second_text))
    except json.JSONDecodeError:
        return first_text == second_text


def drifted(first_dir, second_dir):
    """Return the names of the artefacts that differ between the two runs."""
    first_dir = Path(first_dir)
    second_dir = Path(second_dir)
    drifted_names = []
    for path in sorted(second_dir.glob("*.json")):
        other = first_dir / path.name
        if not other.exists():
            drifted_names.append(path.name)
            continue
        if not same_artefact(other.read_text(), path.read_text()):
            drifted_names.append(path.name)
    return drifted_names


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", help="the artefacts of the first run")
    parser.add_argument("second", help="the artefacts of the second run")
    args = parser.parse_args(argv)

    drifted_names = drifted(args.first, args.second)
    if drifted_names:
        print(f"published artefacts are not reproducible: {drifted_names}")
        return 1
    count = len(list(Path(args.second).glob("*.json")))
    print(f"all {count} published artefacts are reproducible")
    return 0


if __name__ == "__main__":
    sys.exit(main())

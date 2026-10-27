#!/usr/bin/env python3
"""End-to-end pipeline: deliver -> ingest -> validate -> build -> trust -> publish.

This is the script CI runs and the script a scheduler runs. It is the same
pipeline as ``python -m orchestration.pipeline`` and it fails loudly: a broken
expectation stops the run instead of publishing a number nobody can trust.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestration.pipeline import run  # noqa: E402


def main() -> int:
    run(include_delivery="--no-delivery" not in sys.argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

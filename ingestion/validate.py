"""Backward-compatible entry point for contract validation.

The canonical contract implementation lives in :mod:`ingestion.contracts`.
This module previously carried a second, drifting copy of the rules; it now
delegates so validation logic exists in exactly one place.
"""
from typing import Any, Dict, Iterable, List

from .contracts import (  # noqa: F401
    CONTRACT_VERSION,
    SOURCES,
    SOURCES_ORDER,
    get_contract,
    normalize_row,
    row_is_valid,
    validate_rows,
)

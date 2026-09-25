"""Canonical JSON and content hashes.

A content hash is sha256 over canonical JSON: sorted keys, no whitespace, Decimals as
strings, datetimes as UTC ISO-8601. Floats are rejected so a hash never depends on
float formatting.
"""

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any


def _default(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("naive datetime cannot be hashed; use timezone-aware UTC")
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"cannot canonicalise {type(value).__name__}")


def _reject_floats(value: Any) -> None:
    if isinstance(value, float):
        raise TypeError("floats are not allowed in hashed content; use Decimal or str")
    if isinstance(value, dict):
        for v in value.values():
            _reject_floats(v)
    elif isinstance(value, list | tuple):
        for v in value:
            _reject_floats(v)


def canonical_json(value: Any) -> str:
    _reject_floats(value)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_default
    )


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()

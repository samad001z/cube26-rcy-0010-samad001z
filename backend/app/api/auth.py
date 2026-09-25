"""API keys. Each key maps to exactly one organisation; the organisation used for row-level
security comes from the key and from nothing in the request.

Keys are configured as `ALIBI_API_KEYS=org_id:sha256hex,org_id:sha256hex`: only the SHA-256
of each key is stored, never the key. A presented key is hashed and compared against every
configured hash with hmac.compare_digest. `alibi api-key --org <org>` makes a new key.
"""

import hashlib
import hmac
import re
import secrets
from collections.abc import Mapping
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.core.config import get_settings

API_KEY_HEADER = "X-API-Key"
_HASH = re.compile(r"^[0-9a-f]{64}$")
_ORG = re.compile(r"^[A-Za-z0-9_.-]+$")


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def new_key() -> str:
    return secrets.token_urlsafe(32)


def parse_api_keys(value: str) -> dict[str, str]:
    """`org:sha256hex,...` -> {sha256hex: org}. Refuses a malformed entry or a hash listed
    twice, so a key can never map to two organisations."""
    keys: dict[str, str] = {}
    for n, entry in enumerate((e.strip() for e in value.split(",")), start=1):
        if not entry:
            continue
        org, sep, digest = entry.partition(":")
        org, digest = org.strip(), digest.strip().lower()
        if not sep or not _ORG.match(org) or not _HASH.match(digest):
            raise ValueError(f"ALIBI_API_KEYS entry {n} is not org_id:sha256hex")
        if digest in keys:
            raise ValueError(f"ALIBI_API_KEYS entry {n} repeats a key hash")
        keys[digest] = org
    return keys


def org_for_key(presented: str | None, keys: Mapping[str, str]) -> str | None:
    """The organisation of a presented key, or None. Compares against every configured hash
    without stopping early."""
    if not presented:
        return None
    digest = hash_key(presented)
    found: str | None = None
    for configured, org in keys.items():
        if hmac.compare_digest(configured, digest):
            found = org
    return found


def configured_keys() -> dict[str, str]:
    return parse_api_keys(get_settings().alibi_api_keys)


def require_org(
    keys: Annotated[dict[str, str], Depends(configured_keys)],
    x_api_key: Annotated[str | None, Header(alias=API_KEY_HEADER)] = None,
) -> str:
    org = org_for_key(x_api_key, keys)
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return org

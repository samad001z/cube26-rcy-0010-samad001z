from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.hashing import canonical_json, content_hash


def test_key_order_does_not_change_hash():
    assert content_hash({"a": 1, "b": [1, 2]}) == content_hash({"b": [1, 2], "a": 1})


def test_value_change_changes_hash():
    assert content_hash({"a": 1}) != content_hash({"a": 2})


def test_decimal_and_datetime_are_canonical():
    ist = timezone(timedelta(hours=5, minutes=30))
    a = {"x": Decimal("1.50"), "t": datetime(2026, 6, 4, 12, 0, tzinfo=UTC)}
    b = {"x": Decimal("1.50"), "t": datetime(2026, 6, 4, 17, 30, tzinfo=ist)}
    assert content_hash(a) == content_hash(b)
    assert canonical_json(a) == '{"t":"2026-06-04T12:00:00Z","x":"1.50"}'


def test_floats_and_naive_datetimes_rejected():
    with pytest.raises(TypeError):
        content_hash({"x": 1.5})
    with pytest.raises(ValueError):
        content_hash({"t": datetime(2026, 1, 1)})


json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(),
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(st.text(), children, max_size=4)
    ),
    max_leaves=12,
)


@given(json_values)
def test_hash_is_deterministic_and_hex(value):
    h = content_hash(value)
    assert h == content_hash(value)
    assert len(h) == 64
    int(h, 16)

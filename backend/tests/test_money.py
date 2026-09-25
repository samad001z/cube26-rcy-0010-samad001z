from decimal import Decimal

import pytest

from app.core.money import to_money


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("4.25", "4.25"), ("0", "0.00"), ("0.00", "0.00"), (" 12.5 ", "12.50"), (3, "3.00")],
)
def test_to_money(raw, expected):
    assert to_money(raw) == Decimal(expected)


def test_rounds_half_even_to_cents():
    assert to_money("0.125") == Decimal("0.12")
    assert to_money("0.135") == Decimal("0.14")


@pytest.mark.parametrize("bad", [1.5, True, "abc", "", "NaN", "Infinity"])
def test_rejects_bad_input(bad):
    with pytest.raises((TypeError, ValueError)):
        to_money(bad)

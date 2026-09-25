"""Money is Decimal. Floats are refused."""

from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

CENT = Decimal("0.01")


def to_money(value: str | int | Decimal) -> Decimal:
    """Parse to a Decimal quantised to cents. Rejects floats and non-numeric text."""
    if isinstance(value, float | bool):
        raise TypeError("money must not be a float or bool; pass a str, int or Decimal")
    try:
        dec = Decimal(value.strip() if isinstance(value, str) else value)
    except InvalidOperation as exc:
        raise ValueError(f"not a valid amount: {value!r}") from exc
    if not dec.is_finite():
        raise ValueError(f"amount must be finite: {value!r}")
    return dec.quantize(CENT, rounding=ROUND_HALF_EVEN)

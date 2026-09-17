"""Normalizer agent: turns whatever a page printed into (minor units, ISO currency).

Storefronts print money in a dozen ways. Everything downstream (history, alerts, the
dashboard) assumes `price_cents` is an int in the store's currency. This is the only place
that should know about currency symbols and locale formatting.
"""
from __future__ import annotations

import re
from typing import Optional

SYMBOLS = {
    "$": "USD",
    "US$": "USD",
    "€": "EUR",
    "£": "GBP",
    "₹": "INR",
    "kr": "SEK",
    "¥": "JPY",
    "CHF": "CHF",
}

CODES = {"USD", "EUR", "GBP", "INR", "SEK", "NOK", "DKK", "JPY", "CHF", "CAD", "AUD"}


def detect_currency(text: str, default: Optional[str] = None) -> Optional[str]:
    t = text.strip()

    for code in CODES:
        if re.search(rf"\b{code}\b", t):
            return code

    for sym, code in sorted(SYMBOLS.items(), key=lambda kv: -len(kv[0])):
        if sym in t:
            return code

    return default


def parse_money(
    text: str, default_currency: Optional[str] = None
) -> tuple[Optional[int], Optional[str]]:
    """Parse a printed price into minor currency units."""

    if text is None:
        return None, default_currency

    currency = detect_currency(text, default_currency)
    normalized = re.sub(r"[^\d,\.]", "", text)

    if not normalized:
        return None, currency

    # European decimal format: 720,92 -> 720.92
    if "," in normalized and "." not in normalized:
        parts = normalized.split(",")
        if len(parts) == 2 and len(parts[1]) == 2:
            normalized = f"{parts[0]}.{parts[1]}"
        else:
            normalized = normalized.replace(",", "")

    # US format: 1,299.00 -> 1299.00
    elif "," in normalized and "." in normalized:
        normalized = normalized.replace(",", "")

    try:
        amount = float(normalized)
    except ValueError:
        return None, currency

    return int(round(amount * 100)), currency


def unit_price(
    price_cents: Optional[int], pack_size: int
) -> Optional[int]:
    if price_cents is None or pack_size <= 1:
        return None

    return int(round(price_cents / pack_size))
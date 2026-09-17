"""Watcher agent: compares new observations against history and raises alerts.

History is a list of observations ordered by `observed_at`. Rules come from alerts.yaml.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Iterable

from ..models import Alert, Observation


def _key(o: Observation) -> tuple[str, str]:
    return (o.store, o.product_id)


def _by_product(history: Iterable[Observation]) -> dict[tuple[str, str], list[Observation]]:
    out: dict[tuple[str, str], list[Observation]] = defaultdict(list)
    for o in history:
        out[_key(o)].append(o)
    for v in out.values():
        v.sort(key=lambda o: o.observed_at)
    return out


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def rule_drop_pct(prev: Observation, cur: Observation, pct: float) -> Alert | None:
    if prev.price_cents is None or cur.price_cents is None:
        return None
    if cur.price_cents >= prev.price_cents:
        return None
    drop = (prev.price_cents - cur.price_cents) / prev.price_cents * 100
    if drop >= pct:
        return Alert(store=cur.store, product_id=cur.product_id, rule="drop_pct",
                     message=f"{cur.name or cur.product_id}: {prev.price_cents} -> {cur.price_cents} ({drop:.1f}% drop)",
                     previous_cents=prev.price_cents, current_cents=cur.price_cents, observed_at=cur.observed_at)
    return None


def rule_below_median(prior: list[Observation], cur: Observation, pct: float, window_days: float) -> Alert | None:
    if cur.price_cents is None:
        return None
    cutoff = _dt(cur.observed_at) - timedelta(days=window_days)
    prior_window = []
    for prev in prior:
        if prev.price_cents is None:
            continue
        if prev.currency != cur.currency:
            return None
        dt = _dt(prev.observed_at)
        if dt < cutoff:
            continue
        prior_window.append(prev.price_cents)
    if len(prior_window) < 3:
        return None
    median = int(round(statistics.median(prior_window)))
    threshold = median * (1.0 - (pct / 100.0))
    if cur.price_cents > threshold:
        return None
    return Alert(store=cur.store, product_id=cur.product_id, rule="below_median",
                 message=f"{cur.name or cur.product_id}: {cur.price_cents} <= median {median} ({pct:.0f}% below)",
                 previous_cents=median, current_cents=cur.price_cents, observed_at=cur.observed_at)


def evaluate(history: list[Observation], new: list[Observation], rules: list[dict]) -> list[Alert]:
    """Evaluate `rules` for each observation in `new` against `history` (which must not include `new`)."""
    alerts: list[Alert] = []
    hist = _by_product(history)
    for cur in sorted(new, key=lambda o: o.observed_at):
        prior = hist.get(_key(cur), [])
        prev = prior[-1] if prior else None
        choices: dict[str, Alert | None] = {}
        for rule in rules:
            kind = rule.get("type")
            if kind == "drop_pct" and prev is not None:
                choices["drop_pct"] = rule_drop_pct(prev, cur, float(rule.get("pct", 10)))
            elif kind == "below_median":
                choices["below_median"] = rule_below_median(prior, cur, float(rule.get("pct", 15)), float(rule.get("window_days", 30)))
        if choices.get("below_median") is not None:
            alerts.append(choices["below_median"])
        elif choices.get("drop_pct") is not None:
            alerts.append(choices["drop_pct"])
        hist[_key(cur)] = prior + [cur]
    return alerts

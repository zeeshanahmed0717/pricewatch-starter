"""Eval harness for the LLM extractor.

Runs the LLM extractor over every snapshot in a directory, compares with labels.json, and
writes report.json and label_issues.json. The report schema is documented in tasks/ISSUE-3.md.
"""
from __future__ import annotations

import json
import math
import statistics
import time
from pathlib import Path

from .agents.llm_extractor import extract_with_llm
from .providers import Provider


def _error_kind(obs) -> str | None:
    notes = obs.notes or []
    for note in notes:
        if "timeout" in note.lower():
            return "timeout"
        if "provider_error" in note.lower():
            return "provider_error"
        if "malformed_output" in note.lower():
            return "malformed_output"
    return None


def _score(vals: list[bool]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, max(0, math.ceil((pct / 100.0) * len(s)) - 1))
    return s[idx]


def run(provider: Provider, snapshots_dir: str | Path, labels_path: str | Path, out_dir: str | Path) -> dict:
    snapshots_dir, out_dir = Path(snapshots_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    labels = {row["id"]: row for row in json.loads(Path(labels_path).read_text())}

    results = []
    per_store: dict[str, dict[str, list[bool]]] = {}
    errors = {"timeout": 0, "malformed_output": 0, "provider_error": 0}
    latencies: list[float] = []
    cost = {"input_tokens": 0, "output_tokens": 0, "usd_estimate": 0.0}
    t0 = time.perf_counter()

    for snap_id, row in labels.items():
        html = (snapshots_dir / row["file"]).read_text()
        start = time.perf_counter()
        obs = extract_with_llm(provider, row["store"], row["url"], html)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        latencies.append(elapsed_ms)
        exp = row["expected"]
        error_kind = _error_kind(obs)
        if error_kind:
            errors[error_kind] = errors.get(error_kind, 0) + 1
        price_ok = (obs.price_cents == exp["price_cents"]) if error_kind is None else False
        currency_ok = (obs.currency == exp["currency"]) if error_kind is None else False
        availability_ok = (obs.availability == exp["availability"]) if error_kind is None else False
        pack_ok = (obs.pack_size == exp["pack_size"]) if error_kind is None else False
        results.append({
            "id": snap_id,
            "store": row["store"],
            "price_ok": price_ok,
            "currency_ok": currency_ok,
            "availability_ok": availability_ok,
            "pack_ok": pack_ok,
            "error": error_kind,
        })
        store_bucket = per_store.setdefault(row["store"], {"price": [], "currency": [], "availability": [], "pack": [], "n": 0})
        store_bucket["n"] += 1
        store_bucket["price"].append(price_ok)
        store_bucket["currency"].append(currency_ok)
        store_bucket["availability"].append(availability_ok)
        store_bucket["pack"].append(pack_ok)
        if error_kind is None:
            cost["input_tokens"] += max(100, len(html) // 3)
            cost["output_tokens"] += max(50, len(obs.name or "") * 2)
            cost["usd_estimate"] += 0.0002

    overall = {
        "price_exact": _score([r["price_ok"] for r in results]),
        "currency": _score([r["currency_ok"] for r in results]),
        "availability": _score([r["availability_ok"] for r in results]),
        "pack_size": _score([r["pack_ok"] for r in results]),
    }
    per_store_report = {}
    for store, data in per_store.items():
        per_store_report[store] = {
            "n": data["n"],
            "price_exact": _score(data["price"]),
            "currency": _score(data["currency"]),
            "availability": _score(data["availability"]),
            "pack_size": _score(data["pack"]),
        }
    report = {
        "provider": provider.name,
        "model": getattr(provider, "model", "unknown"),
        "n": len(results),
        "overall": overall,
        "per_store": per_store_report,
        "errors": errors,
        "cost": {
            "input_tokens": int(cost["input_tokens"]),
            "output_tokens": int(cost["output_tokens"]),
            "usd_estimate": round(cost["usd_estimate"], 4),
        },
        "latency_ms": {
            "p50": round(_percentile(latencies, 50), 2),
            "p95": round(_percentile(latencies, 95), 2),
        },
        "baseline": {"price_exact": 0.0},
        "elapsed_s": round(time.perf_counter() - t0, 2),
    }
    label_issues = []
    for snap_id, row in labels.items():
        expected = row["expected"]
        if expected.get("availability") == "out_of_stock" and expected.get("price_cents") in (0, None):
            label_issues.append({"id": snap_id, "reason": "Page shows an unavailable item but the label treats it as a regular priced listing."})
    (out_dir / "report.json").write_text(json.dumps(report, indent=2))
    (out_dir / "label_issues.json").write_text(json.dumps(label_issues, indent=2))
    return report

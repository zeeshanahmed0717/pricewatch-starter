"""LLM extractor: the fallback for stores we have no adapter for.

Given raw HTML and its URL, ask a model for the structured offer.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from bs4 import BeautifulSoup

from ..models import Observation
from ..providers import Provider, ProviderError

SYSTEM = """You extract e-commerce offer data from a product page and answer ONLY with a JSON object:
{"name": str|null, "price_cents": int|null, "currency": "ISO-4217"|null, "availability": "in_stock"|"out_of_stock"|"unknown",
 "pack_size": int, "compare_at_cents": int|null}
price_cents is the price of the pack actually being sold, in minor units. If there is no price, use null."""


def _cache_dir() -> Path:
    return Path(os.environ.get("PRICEWATCH_CACHE_DIR", Path.home() / ".pricewatch-cache"))


def _cache_key(provider_name: str, store: str, url: str) -> str:
    return hashlib.sha256(f"{provider_name}|{store}|{url}|{SYSTEM}".encode()).hexdigest()


def cache_read(provider_name: str, store: str, url: str) -> str | None:
    p = _cache_dir() / f"{_cache_key(provider_name, store, url)}.json"
    try:
        if p.exists():
            return p.read_text()
    except OSError:
        pass
    return None


def cache_write(provider_name: str, store: str, url: str, payload: str) -> None:
    try:
        p = _cache_dir() / f"{_cache_key(provider_name, store, url)}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(payload)
    except OSError:
        pass


def clean_html(html: str, limit: int = 12000) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "svg"]):
        t.decompose()
    text = re.sub(r"\n\s*\n+", "\n", soup.get_text("\n"))
    return text[:limit]


def extract_with_llm(provider: Provider, store: str, url: str, html: str, timeout: float = 30.0) -> Observation:
    user = f"URL: {url}\n\nPAGE TEXT:\n{clean_html(html)}"
    metadata = {"source_url": url, "store": store}
    raw = cache_read(provider.name, store, url)
    if raw is None:
        try:
            raw = provider.complete(SYSTEM, user, metadata=metadata, timeout=timeout)
            cache_write(provider.name, store, url, raw)
        except ProviderError as exc:
            return Observation(
                store=store, product_id=url.rstrip("/").split("/")[-1], url=url, name="",
                price_cents=None, currency="", compare_at_cents=None, availability="unknown",
                pack_size=1, source="llm", notes=[f"provider_error:{type(exc).__name__}:{exc}"],
            )
    if raw is None or not raw.strip():
        return Observation(
            store=store, product_id=url.rstrip("/").split("/")[-1], url=url, name="",
            price_cents=None, currency="", compare_at_cents=None, availability="unknown",
            pack_size=1, source="llm", notes=["malformed_output:empty_response"],
        )
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("payload is not an object")
    except (json.JSONDecodeError, TypeError, ValueError):
        return Observation(
            store=store, product_id=url.rstrip("/").split("/")[-1], url=url, name="",
            price_cents=None, currency="", compare_at_cents=None, availability="unknown",
            pack_size=1, source="llm", notes=["malformed_output:invalid_json"],
        )
    return Observation(
        store=store, product_id=url.rstrip("/").split("/")[-1], url=url, name=data.get("name") or "",
        price_cents=data.get("price_cents"), currency=data.get("currency") or "",
        compare_at_cents=data.get("compare_at_cents"), availability=data.get("availability") or "unknown",
        pack_size=int(data.get("pack_size") or 1), source="llm",
    )

"""Price adapter — free public endpoints, no key required.

Tries several venues in order and uses the first that answers. Binance is
listed last on purpose: it returns HTTP 451 (geo-blocked) from a number of
regions including this one, so leading with it guarantees a slow failure.
Kraken and Coinbase Exchange are both open and unauthenticated.

Returns recent closes so the loop can compute RSI without a second call.
"""
from __future__ import annotations

import os

import httpx

from ..common import SchemaError, log  # noqa: F401  (SchemaError used by contract)

SCHEMA_VERSION = 1


def _normalise(asset: str) -> tuple[str, str]:
    base, _, quote = asset.partition("/")
    return base.upper(), (quote or "USDT").upper()


async def _kraken(client: httpx.AsyncClient, asset: str, limit: int) -> dict | None:
    base, quote = _normalise(asset)
    # Kraken uses XBT for bitcoin.
    kbase = "XBT" if base == "BTC" else base
    pair = f"{kbase}{quote}"

    resp = await client.get(
        "https://api.kraken.com/0/public/OHLC",
        params={"pair": pair, "interval": 1},
    )
    resp.raise_for_status()
    payload = resp.json()

    if payload.get("error"):
        return None
    result = payload.get("result") or {}
    series = next((v for k, v in result.items() if k != "last"), None)
    if not series:
        return None

    rows = series[-limit:]
    return {
        "source": "kraken",
        "closes": [float(r[4]) for r in rows],
        "highs": [float(r[2]) for r in rows],
        "lows": [float(r[3]) for r in rows],
    }


async def _coinbase(client: httpx.AsyncClient, asset: str, limit: int) -> dict | None:
    base, quote = _normalise(asset)
    # Coinbase Exchange quotes USD, not USDT.
    product = f"{base}-{'USD' if quote in ('USDT', 'USDC', 'USD') else quote}"

    resp = await client.get(
        f"https://api.exchange.coinbase.com/products/{product}/candles",
        params={"granularity": 60},
        headers={"User-Agent": "hermes-trading/1.0"},
    )
    resp.raise_for_status()
    rows = resp.json()

    if not isinstance(rows, list) or not rows:
        return None
    # Coinbase returns newest-first: [time, low, high, open, close, volume]
    rows = sorted(rows, key=lambda r: r[0])[-limit:]
    return {
        "source": "coinbase",
        "closes": [float(r[4]) for r in rows],
        "highs": [float(r[2]) for r in rows],
        "lows": [float(r[1]) for r in rows],
    }


async def _binance(client: httpx.AsyncClient, asset: str, limit: int) -> dict | None:
    base, quote = _normalise(asset)
    interval = os.environ.get("PRICE_INTERVAL", "1m")

    resp = await client.get(
        "https://api.binance.com/api/v3/klines",
        params={"symbol": f"{base}{quote}", "interval": interval, "limit": limit},
    )
    resp.raise_for_status()
    rows = resp.json()

    if not isinstance(rows, list) or not rows:
        return None
    return {
        "source": "binance",
        "closes": [float(r[4]) for r in rows],
        "highs": [float(r[2]) for r in rows],
        "lows": [float(r[3]) for r in rows],
    }


_VENUES = (("kraken", _kraken), ("coinbase", _coinbase), ("binance", _binance))


async def fetch(asset: str = "BTC/USDT", limit: int = 100) -> dict:
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=15) as client:
        for name, handler in _VENUES:
            try:
                data = await handler(client, asset, limit)
            except Exception as exc:  # geo-block, rate limit, outage
                errors.append(f"{name}: {type(exc).__name__} {exc}")
                continue

            if not data or not data.get("closes"):
                errors.append(f"{name}: empty series")
                continue

            return {
                "schema_version": SCHEMA_VERSION,
                "source": data["source"],
                "asset": asset,
                "price": data["closes"][-1],
                "closes": data["closes"],
                "highs": data["highs"],
                "lows": data["lows"],
            }

    # Transient (all venues down / rate-limited), NOT a schema problem — raise a
    # plain error so the loop's retry + circuit-breaker handles it rather than
    # halting the worker permanently.
    raise RuntimeError("price: no venue returned usable data -> " + " | ".join(errors))

"""Macro adapter — free Coinbase spot as a cross-venue reference price."""
from __future__ import annotations

import httpx

from ..common import SchemaError

SCHEMA_VERSION = 1


async def fetch(asset: str = "BTC/USDT") -> dict:
    base = asset.split("/")[0].upper()

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"https://api.coinbase.com/v2/prices/{base}-USD/spot")
        resp.raise_for_status()
        data = resp.json()

    amount = (data or {}).get("data", {}).get("amount")
    if amount is None:
        raise SchemaError(f"macro: unexpected coinbase payload: {data!r}")

    return {
        "schema_version": SCHEMA_VERSION,
        "source": "coinbase",
        "reference_price": float(amount),
    }

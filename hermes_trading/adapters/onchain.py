"""On-chain adapter — free public endpoint (mempool.space), Glassnode if keyed."""
from __future__ import annotations

import os

import httpx

from ..common import SchemaError

SCHEMA_VERSION = 1


async def fetch(asset: str = "BTC/USDT") -> dict:
    key = os.environ.get("GLASSNODE_API_KEY", "").strip()

    async with httpx.AsyncClient(timeout=15) as client:
        if key:
            resp = await client.get(
                "https://api.glassnode.com/v1/metrics/fees/gas_price_mean",
                params={"a": "BTC", "api_key": key},
            )
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list):
                raise SchemaError("onchain: glassnode payload not a list")
            return {
                "schema_version": SCHEMA_VERSION,
                "source": "glassnode",
                "fee_mean": (data[-1].get("v") if data else None),
            }

        resp = await client.get("https://mempool.space/api/v1/fees/recommended")
        resp.raise_for_status()
        data = resp.json()

    if not isinstance(data, dict) or "fastestFee" not in data:
        raise SchemaError(f"onchain: unexpected mempool payload: {data!r}")

    return {
        "schema_version": SCHEMA_VERSION,
        "source": "mempool.space",
        "fastest_fee": data.get("fastestFee"),
        "hour_fee": data.get("hourFee"),
    }

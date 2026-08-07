"""News adapter — free Alternative.me Fear & Greed index; NewsAPI if keyed."""
from __future__ import annotations

import os

import httpx

from ..common import SchemaError

SCHEMA_VERSION = 1


async def fetch(asset: str = "BTC/USDT") -> dict:
    key = os.environ.get("NEWS_API_KEY", "").strip()

    async with httpx.AsyncClient(timeout=15) as client:
        if key:
            resp = await client.get(
                "https://newsapi.org/v2/everything",
                params={"q": "bitcoin", "pageSize": 10, "apiKey": key},
            )
            resp.raise_for_status()
            data = resp.json()
            if "articles" not in data:
                raise SchemaError("news: newsapi payload missing 'articles'")
            return {
                "schema_version": SCHEMA_VERSION,
                "source": "newsapi",
                "headline_count": len(data["articles"]),
            }

        resp = await client.get("https://api.alternative.me/fng/?limit=1")
        resp.raise_for_status()
        data = resp.json()

    rows = data.get("data") if isinstance(data, dict) else None
    if not rows:
        raise SchemaError(f"news: unexpected fng payload: {data!r}")

    return {
        "schema_version": SCHEMA_VERSION,
        "source": "alternative.me_fng",
        "fear_greed": int(rows[0]["value"]),
        "classification": rows[0].get("value_classification"),
    }

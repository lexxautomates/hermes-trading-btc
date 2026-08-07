"""Adapter registry. Each module exposes `async def fetch(asset) -> dict`."""
from . import macro, news, onchain, price

ALL = {
    "price": price,
    "onchain": onchain,
    "news": news,
    "macro": macro,
}

# Schema versions the loop is built against. A mismatch halts the loop
# rather than silently trading on a payload we no longer understand.
EXPECTED_SCHEMA = {
    "price": price.SCHEMA_VERSION,
    "onchain": onchain.SCHEMA_VERSION,
    "news": news.SCHEMA_VERSION,
    "macro": macro.SCHEMA_VERSION,
}

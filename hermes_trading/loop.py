"""24/7 reliability loop: fetch -> evaluate -> paper-trade -> log -> heartbeat.

Per-adapter retries (3, exponential backoff). Circuit-breaks after 5
consecutive cycle failures. A SchemaError is never retried — an adapter whose
payload shape changed is a correctness problem, so the loop halts immediately
rather than trading on data it can't interpret.
"""
from __future__ import annotations

import asyncio
import random
import uuid
from datetime import datetime, timezone
from typing import Any

from .adapters import ALL as ADAPTERS
from .adapters import EXPECTED_SCHEMA
from .common import (
    HEARTBEAT_PATH,
    STRATEGY_PATH,
    TRADES_PATH,
    SchemaError,
    append_jsonl,
    load_yaml,
    log,
    read_jsonl,
    utcnow,
    write_json,
)
from .score import metrics

MAX_CONSECUTIVE_FAILURES = 5
CYCLE_SECONDS = 60


def rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for prev, cur in zip(closes[-(period + 1):-1], closes[-period:]):
        delta = cur - prev
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


async def fetch_with_retry(name: str, mod: Any, asset: str, attempts: int = 3) -> dict:
    delay = 1.0
    last: Exception | None = None
    for i in range(attempts):
        try:
            data = await mod.fetch(asset)
            got = data.get("schema_version")
            want = EXPECTED_SCHEMA[name]
            if got != want:
                raise SchemaError(f"{name}: schema_version {got!r}, expected {want!r}")
            return data
        except SchemaError:
            raise  # never retry a schema mismatch
        except Exception as exc:  # transient: network, rate limit, 5xx
            last = exc
            if i < attempts - 1:
                await asyncio.sleep(delay)
                delay *= 2
    raise RuntimeError(f"{name}: failed after {attempts} attempts: {last}")


def evaluate(strategy: dict, snapshot: dict) -> tuple[bool, str]:
    entry = strategy.get("entry", {}) or {}
    indicator = entry.get("indicator", "rsi")
    threshold = float(entry.get("threshold", 30))
    direction = entry.get("direction", "long")

    if indicator != "rsi":
        return False, f"unsupported indicator {indicator!r}"

    value = snapshot.get("rsi")
    if value is None:
        return False, "rsi unavailable (insufficient history)"

    if direction == "long":
        return (value <= threshold), f"rsi={value:.2f} vs <= {threshold}"
    return (value >= threshold), f"rsi={value:.2f} vs >= {threshold}"


def simulate_trade(strategy: dict, snapshot: dict, asset: str) -> dict:
    """Paper trade only. Exit is modelled one cycle forward from entry price
    using observed short-horizon volatility — never a real order."""
    entry_price = float(snapshot["price"])
    closes = snapshot["closes"]

    window = closes[-20:] if len(closes) >= 20 else closes
    if len(window) >= 2:
        rets = [
            (window[i] - window[i - 1]) / window[i - 1]
            for i in range(1, len(window))
            if window[i - 1]
        ]
        sigma = (sum(r * r for r in rets) / len(rets)) ** 0.5 if rets else 0.002
    else:
        sigma = 0.002

    stop_pct = float(strategy.get("stop_loss_pct", 2.0)) / 100.0
    size_r = float(strategy.get("position_size_r", 0.5))
    direction = (strategy.get("entry", {}) or {}).get("direction", "long")

    drift = random.gauss(0.0, sigma)
    move = -drift if direction == "short" else drift
    move = max(move, -stop_pct)  # stop-loss caps the downside

    exit_price = entry_price * (1.0 + move)
    pnl_pct = move * size_r

    return {
        "id": f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:4]}",
        "ts": int(datetime.now(timezone.utc).timestamp()),
        "asset": asset,
        "mode": "paper",
        "direction": direction,
        "entry_price": round(entry_price, 2),
        "exit_price": round(exit_price, 2),
        "sigma": round(sigma, 6),
        "stop_loss_pct": stop_pct * 100,
        "position_size_r": size_r,
        "pnl_pct": round(pnl_pct, 6),
        "rsi_at_entry": round(snapshot["rsi"], 2) if snapshot.get("rsi") else None,
        "strategy_version": str(strategy.get("version", "01")),
        "closed": True,
        "result": "win" if pnl_pct > 0 else "loss",
    }


async def run_loop(asset: str, cycles: int | None = None, interval: int | None = None) -> None:
    """Run the trading loop.

    cycles=None  -> run forever (long-lived host: VM, Docker, local).
    cycles=N     -> run exactly N cycles then return cleanly. Used by CI
                    runners (GitHub Actions) which are time-boxed and must
                    exit so the job can commit state back to the repo.
    """
    sleep_s = CYCLE_SECONDS if interval is None else interval
    log(f"Booting hermes-trading worker — asset={asset} mode=paper "
        f"cycles={'forever' if cycles is None else cycles} interval={sleep_s}s")
    consecutive_failures = 0
    completed = 0

    while True:
        cycle_started = utcnow()
        try:
            strategy = load_yaml(STRATEGY_PATH)

            results: dict[str, Any] = {}
            for name, mod in ADAPTERS.items():
                try:
                    results[name] = await fetch_with_retry(name, mod, asset)
                except SchemaError:
                    raise
                except Exception as exc:
                    # A non-price adapter is advisory; the loop survives without it.
                    if name == "price":
                        raise
                    log(f"  ! {name} adapter unavailable: {exc}")
                    results[name] = None

            price_data = results["price"]
            snapshot = {
                "price": price_data["price"],
                "closes": price_data["closes"],
                "rsi": rsi(price_data["closes"]),
            }

            fired, reason = evaluate(strategy, snapshot)

            if fired:
                trade = simulate_trade(strategy, snapshot, asset)
                append_jsonl(TRADES_PATH, trade)
                log(
                    f"[TRADE] {trade['direction']} {asset} @ {trade['entry_price']} "
                    f"-> {trade['exit_price']} pnl={trade['pnl_pct']*100:+.3f}% "
                    f"({trade['result']}) v{trade['strategy_version']}"
                )
            else:
                log(f"[FLAT] {asset}={snapshot['price']} — no entry ({reason})")

            all_trades = read_jsonl(TRADES_PATH)
            m = metrics(all_trades)
            write_json(
                HEARTBEAT_PATH,
                {
                    "last_cycle": cycle_started,
                    "asset": asset,
                    "price": snapshot["price"],
                    "rsi": snapshot["rsi"],
                    "strategy_version": str(strategy.get("version", "01")),
                    "entry_fired": fired,
                    "reason": reason,
                    "metrics": m,
                    "status": "ok",
                },
            )
            consecutive_failures = 0

        except SchemaError as exc:
            log(f"[HALT] schema mismatch — refusing to trade on data I can't read: {exc}")
            write_json(
                HEARTBEAT_PATH,
                {"last_cycle": cycle_started, "status": "halted_schema_error", "error": str(exc)},
            )
            raise SystemExit(2)

        except Exception as exc:
            consecutive_failures += 1
            log(f"[ERROR] cycle failed ({consecutive_failures}/{MAX_CONSECUTIVE_FAILURES}): {exc}")
            write_json(
                HEARTBEAT_PATH,
                {
                    "last_cycle": cycle_started,
                    "status": "degraded",
                    "consecutive_failures": consecutive_failures,
                    "error": str(exc),
                },
            )
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                log("[HALT] circuit breaker tripped — worker stopping for supervisor restart")
                raise SystemExit(1)

        completed += 1
        if cycles is not None and completed >= cycles:
            log(f"completed {completed} cycle(s) — exiting cleanly")
            return

        await asyncio.sleep(sleep_s)

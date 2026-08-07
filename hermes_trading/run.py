"""Entrypoint. Reads asset from goal.yaml; --asset overrides."""
from __future__ import annotations

import argparse
import asyncio
import os

from .common import GOAL_PATH, load_yaml, log
from .loop import run_loop


def main() -> None:
    parser = argparse.ArgumentParser(prog="hermes_trading.run")
    parser.add_argument("--asset", default=None, help="ccxt ticker, e.g. BTC/USDT")
    parser.add_argument("--cycles", type=int, default=None,
                        help="run N cycles then exit (CI runners); default: forever")
    parser.add_argument("--interval", type=int, default=None,
                        help="seconds between cycles (default 60)")
    args = parser.parse_args()

    goal = load_yaml(GOAL_PATH)
    asset = args.asset or goal.get("asset", "BTC/USDT")

    mode = os.environ.get("HERMES_TRADING_MODE", "paper").lower()
    accepted = os.environ.get("HERMES_TRADING_I_ACCEPT_RISK", "false").lower() == "true"

    if mode == "live" and not accepted:
        log("[REFUSE] HERMES_TRADING_MODE=live but HERMES_TRADING_I_ACCEPT_RISK is not true.")
        raise SystemExit(3)
    if mode == "live":
        # The live execution adapter is deliberately not importable yet.
        log("[REFUSE] live execution adapter is not implemented. Paper mode only.")
        raise SystemExit(3)

    log(f"mode={mode} goal={GOAL_PATH}")
    try:
        asyncio.run(run_loop(asset, cycles=args.cycles, interval=args.interval))
    except KeyboardInterrupt:
        log("interrupted — shutting down cleanly")


if __name__ == "__main__":
    main()

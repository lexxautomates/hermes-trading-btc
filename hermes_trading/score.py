"""score(trades, goal) -> float in [-1, +1].

Composite of three components, each normalised to [-1, +1] then weighted:
  * realised return vs target_return_30d   (weight 0.5)
  * max drawdown vs max_drawdown           (weight 0.3)
  * Sharpe vs min_sharpe                   (weight 0.2)

Below goal['failure_below'] the return component is driven steeply negative
so a blown-up strategy can never average its way back to a positive score.
"""
from __future__ import annotations

import math
from typing import Any

W_RETURN, W_DRAWDOWN, W_SHARPE = 0.5, 0.3, 0.2


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def compounded_return(trades: list[dict[str, Any]]) -> float:
    eq = 1.0
    for t in trades:
        eq *= 1.0 + float(t.get("pnl_pct", 0.0))
    return eq - 1.0


def max_drawdown(trades: list[dict[str, Any]]) -> float:
    eq, peak, worst = 1.0, 1.0, 0.0
    for t in trades:
        eq *= 1.0 + float(t.get("pnl_pct", 0.0))
        peak = max(peak, eq)
        if peak > 0:
            worst = min(worst, eq / peak - 1.0)
    return abs(worst)


def sharpe(trades: list[dict[str, Any]]) -> float:
    rets = [float(t.get("pnl_pct", 0.0)) for t in trades]
    n = len(rets)
    if n < 2:
        return 0.0
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / (n - 1)
    sd = math.sqrt(var)
    if sd == 0:
        return 0.0
    # Annualised on a per-trade basis — comparable across cadences.
    return (mean / sd) * math.sqrt(n)


def metrics(trades: list[dict[str, Any]]) -> dict[str, float]:
    closed = [t for t in trades if t.get("closed")]
    return {
        "closed_trades": len(closed),
        "wins": sum(1 for t in closed if float(t.get("pnl_pct", 0)) > 0),
        "losses": sum(1 for t in closed if float(t.get("pnl_pct", 0)) <= 0),
        "compounded_return": compounded_return(closed),
        "max_drawdown": max_drawdown(closed),
        "sharpe": sharpe(closed),
    }


def score(trades: list[dict[str, Any]], goal: dict[str, Any]) -> float:
    closed = [t for t in trades if t.get("closed")]
    if not closed:
        return 0.0

    target = float(goal.get("target_return_30d", 0.05))
    max_dd = float(goal.get("max_drawdown", 0.08))
    min_sh = float(goal.get("min_sharpe", 1.2))
    floor = float(goal.get("failure_below", -0.04))

    ret = compounded_return(closed)
    dd = max_drawdown(closed)
    sh = sharpe(closed)

    # Return: +1 at target, 0 at flat, steeply negative past the floor.
    if ret < floor:
        r_comp = _clamp(-1.0 + (ret - floor) * 5.0)
    else:
        r_comp = _clamp(ret / target) if target else 0.0

    # Drawdown: +1 when flat, 0 at the limit, -1 at twice the limit.
    d_comp = _clamp(1.0 - (dd / max_dd)) if max_dd else 0.0

    # Sharpe: +1 at/above the bar, scaling down to -1 at -min_sharpe.
    s_comp = _clamp(sh / min_sh) if min_sh else 0.0

    return _clamp(W_RETURN * r_comp + W_DRAWDOWN * d_comp + W_SHARPE * s_comp)

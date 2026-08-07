"""Reflection cycle — changes exactly ONE variable per run.

Modes:
  --fallback  deterministic rule. Used before Hermes is installed.
  --hermes    calls the `hermes` CLI as a subprocess, parses its hypothesis.

Both modes: bump version, archive prior to state/history/v{NNNN}.yaml,
append the hypothesis to state/hypotheses.jsonl.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
from typing import Any

from .common import (
    GOAL_PATH,
    HISTORY_DIR,
    HYPOTHESES_PATH,
    STRATEGY_PATH,
    TRADES_PATH,
    append_jsonl,
    load_yaml,
    log,
    read_jsonl,
    save_yaml,
    utcnow,
)
from .score import metrics, score


def _next_version(current: str) -> str:
    try:
        return f"{int(str(current)) + 1:02d}"
    except (TypeError, ValueError):
        return "02"


def _archive(strategy: dict[str, Any]) -> str:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    n = len(list(HISTORY_DIR.glob("v*.yaml"))) + 1
    path = HISTORY_DIR / f"v{n:04d}.yaml"
    save_yaml(path, strategy)
    return str(path)


def _apply(strategy: dict, variable: str, new_value: Any) -> dict:
    updated = copy.deepcopy(strategy)
    if variable == "entry.threshold":
        updated.setdefault("entry", {})["threshold"] = new_value
    elif variable in ("stop_loss_pct", "position_size_r"):
        updated[variable] = new_value
    else:
        raise ValueError(f"refusing to change unknown variable: {variable!r}")
    return updated


def _commit(strategy: dict, hypothesis: dict) -> None:
    archived = _archive(strategy)
    updated = _apply(strategy, hypothesis["variable"], hypothesis["new_value"])
    updated["version"] = _next_version(strategy.get("version", "01"))
    save_yaml(STRATEGY_PATH, updated)

    record = {**hypothesis, "ts": utcnow(),
              "from_version": str(strategy.get("version", "01")),
              "to_version": updated["version"],
              "archived_to": archived}
    append_jsonl(HYPOTHESES_PATH, record)

    log(f"v{record['from_version']} -> v{record['to_version']}: "
        f"{hypothesis['variable']} {hypothesis['old_value']} -> {hypothesis['new_value']}")
    log(f"  rationale: {hypothesis['rationale']}")


def reflect_fallback() -> int:
    strategy = load_yaml(STRATEGY_PATH)
    goal = load_yaml(GOAL_PATH)
    trades = [t for t in read_jsonl(TRADES_PATH) if t.get("closed")]

    if not trades:
        log("no closed trades yet — nothing to reflect on")
        return 1

    m = metrics(trades)
    s = score(trades, goal)
    log(f"trades={m['closed_trades']} return={m['compounded_return']*100:+.3f}% "
        f"dd={m['max_drawdown']*100:.3f}% sharpe={m['sharpe']:.2f} score={s:+.3f}")

    target = float(goal.get("target_return_30d", 0.05))
    max_dd = float(goal.get("max_drawdown", 0.08))

    # Drawdown breach takes priority — protect capital before chasing return.
    if m["max_drawdown"] > max_dd:
        old = float(strategy.get("stop_loss_pct", 2.0))
        new = round(max(0.2, old - 0.2), 2)
        hypothesis = {
            "variable": "stop_loss_pct", "old_value": old, "new_value": new,
            "rationale": (f"drawdown {m['max_drawdown']*100:.2f}% exceeds max "
                          f"{max_dd*100:.2f}% — tightening stop by 0.2"),
            "predicted_direction": "score_up", "source": "deterministic_fallback",
        }
    elif m["compounded_return"] < target:
        old = float((strategy.get("entry", {}) or {}).get("threshold", 30))
        new = round(old + 2, 2)
        hypothesis = {
            "variable": "entry.threshold", "old_value": old, "new_value": new,
            "rationale": (f"return {m['compounded_return']*100:+.2f}% below target "
                          f"{target*100:.2f}% — loosening entry threshold by 2"),
            "predicted_direction": "score_up", "source": "deterministic_fallback",
        }
    else:
        log("goal met and drawdown within limits — no change this cycle")
        return 0

    _commit(strategy, hypothesis)
    return 0


def reflect_hermes(timeout: int = 300) -> int:
    strategy = load_yaml(STRATEGY_PATH)
    goal = load_yaml(GOAL_PATH)
    trades = [t for t in read_jsonl(TRADES_PATH) if t.get("closed")][-25:]

    if not trades:
        log("no closed trades yet — nothing to reflect on")
        return 1

    m = metrics(trades)
    prompt = f"""You are the reflection engine of a self-improving trading agent.

GOAL:
{json.dumps(goal, indent=2)}

CURRENT STRATEGY:
{json.dumps(strategy, indent=2)}

METRICS (last {len(trades)} closed trades):
{json.dumps(m, indent=2, default=str)}

RECENT TRADES:
{json.dumps(trades[-10:], indent=2, default=str)}

Change EXACTLY ONE variable. Allowed: entry.threshold, stop_loss_pct,
position_size_r. Reply with ONLY a JSON object:
{{"variable": "...", "new_value": <number>, "rationale": "...",
  "predicted_direction": "score_up"}}"""

    log("calling hermes for a hypothesis...")
    try:
        proc = subprocess.run(
            ["hermes", "--cli", "-z", prompt],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        log("[ERROR] `hermes` not found on PATH — falling back to deterministic rule")
        return reflect_fallback()
    except subprocess.TimeoutExpired:
        log(f"[ERROR] hermes timed out after {timeout}s — no change applied")
        return 1

    if proc.returncode != 0:
        log(f"[ERROR] hermes exited {proc.returncode}: {proc.stderr[:400]}")
        return 1

    match = re.search(r"\{.*\}", proc.stdout, re.DOTALL)
    if not match:
        log(f"[ERROR] no JSON in hermes output: {proc.stdout[:400]}")
        return 1

    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        log(f"[ERROR] hermes returned malformed JSON: {exc}")
        return 1

    variable = parsed.get("variable")
    if variable == "entry.threshold":
        old = (strategy.get("entry", {}) or {}).get("threshold")
    else:
        old = strategy.get(variable)

    if old is None:
        log(f"[ERROR] hermes named an unknown variable: {variable!r}")
        return 1

    hypothesis = {
        "variable": variable,
        "old_value": old,
        "new_value": parsed["new_value"],
        "rationale": parsed.get("rationale", ""),
        "predicted_direction": parsed.get("predicted_direction", "score_up"),
        "source": "hermes",
    }
    _commit(strategy, hypothesis)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="hermes_trading.reflect")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--fallback", action="store_true", help="deterministic rule")
    group.add_argument("--hermes", action="store_true", help="ask the hermes CLI")
    args = parser.parse_args()

    raise SystemExit(reflect_fallback() if args.fallback else reflect_hermes())


if __name__ == "__main__":
    main()

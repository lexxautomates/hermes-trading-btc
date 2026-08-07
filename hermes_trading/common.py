"""Shared helpers: paths, YAML/JSONL IO, logging, schema errors."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

# /app on Railway, repo root locally. STATE_DIR is the single source of truth.
ROOT = Path(os.environ.get("HERMES_TRADING_ROOT", Path(__file__).resolve().parent.parent))
STATE_DIR = ROOT / "state"
HISTORY_DIR = STATE_DIR / "history"

GOAL_PATH = STATE_DIR / "goal.yaml"
STRATEGY_PATH = STATE_DIR / "strategy.yaml"
TRADES_PATH = STATE_DIR / "trades.jsonl"
HYPOTHESES_PATH = STATE_DIR / "hypotheses.jsonl"
HEARTBEAT_PATH = STATE_DIR / "heartbeat.json"


class SchemaError(RuntimeError):
    """An adapter returned a payload whose schema_version we don't understand."""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


def load_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def save_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False)
    os.replace(tmp, path)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)

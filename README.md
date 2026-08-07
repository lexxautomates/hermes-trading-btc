# hermes-trading-btc

Self-improving paper-trading agent. **Paper mode only — no real orders, ever.**

- **Worker** — pulls live market data, evaluates `state/strategy.yaml`, logs paper trades.
- **Brain** — Hermes reflects on outcomes and rewrites the strategy, one variable at a time.

## Strategy

| | |
|---|---|
| Asset | `BTC/USDT` |
| Target | +5% / 30d |
| Max drawdown | 8% |
| Min Sharpe | 1.2 |
| Reflection cadence | every 5 closed trades |

Success/failure criteria live in `state/goal.yaml` and are **not** edited by the
agent. The agent only evolves `state/strategy.yaml`.

## Free deployment — GitHub Actions

No VM, no PaaS, no card. `.github/workflows/trading-worker.yml` runs on a
schedule, executes a burst of cycles, reflects when enough trades have closed,
and commits state back to the repo. **The repo is the persistence layer** —
Actions runners are ephemeral, so state must round-trip through git.

Public repo = unlimited Actions minutes. Private = 2,000 min/month.

> GitHub's minimum cron granularity is 5 minutes, and scheduled runs are
> best-effort — under load they get delayed or dropped. Fine for a paper
> sampler; not suitable for latency-sensitive execution.

## Run locally

```bash
uv sync
uv run python -m hermes_trading.run                      # forever
uv run python -m hermes_trading.run --cycles 5 --interval 10
uv run python -m hermes_trading.reflect --fallback       # deterministic
uv run python -m hermes_trading.reflect --hermes         # LLM reasoning
```

## Layout

```
hermes_trading/
├── run.py         entrypoint
├── loop.py        24/7 loop, retries, circuit breaker
├── reflect.py     reflection: --fallback | --hermes
├── score.py       score(trades, goal) -> [-1, +1]
└── adapters/      price · onchain · news · macro
state/
├── goal.yaml      success/failure (human-owned)
├── strategy.yaml  evolves: v01 -> v02 -> ...
├── trades.jsonl   every paper trade
├── hypotheses.jsonl  why each change was made
└── history/       every prior strategy version
```

## Data sources

All free, no keys. Price fails over **Kraken → Coinbase → Binance**; Binance is
last because it returns HTTP 451 in many regions. Optional keys in `.env`
(Glassnode, NewsAPI) upgrade sources when present.

## Safety

- Paper mode enforced in `run.py`; live execution adapter is **not implemented**
  and both `.env` flags must flip before it would even be considered.
- Schema mismatch halts the loop rather than trading on misread data.
- Circuit breaker after 5 consecutive failures.
- Reflection changes exactly ONE variable per cycle; prior versions archived.

## Backups

State is tracked here, but for local agents whose state is gitignored, run
`bash snapshot-state.sh` (hourly cron writes to `~/hermes-trading-backups/`).

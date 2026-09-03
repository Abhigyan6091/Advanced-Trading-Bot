# Strategic Trade Analyzer

**Intelligent Trading & Risk Analysis Platform**

A trading platform built around an explicit risk gate. Strategies propose;
they do not execute. Every proposed trade is scored, and approved, resized or
refused with reasons — and the refusals are stored, because "why was this
trade rejected?" is the question the product exists to answer.

> **Simulated trading only.** Real-money execution is not implemented. There is
> no live broker, and `BrokerKind` has no live member — it cannot be enabled by
> configuration.

---

## Pipeline

```
Market Data → Strategy → Signal → Risk Engine → Decision → Order → Execution → Portfolio → Analytics
```

Each stage hands a typed object to the next and nothing skips a stage. The risk
engine is the only thing that can turn a `Signal` into an `Order`, which is what
makes "no trade bypasses risk" a structural property rather than a convention.

The backtester runs the *same* strategy and risk code as the live path against
different market-data and broker implementations. If a backtest and live
trading disagree, that is a bug — not an expected difference.

---

## Status

| Phase | Scope | State |
|-------|-------|-------|
| 0 | Repository audit | ✅ Complete |
| 1 | Foundation, domain models, persistence | ✅ Complete |
| 2 | Market data + strategy engine | ✅ Complete |
| 3 | Risk engine | ✅ Complete |
| 4 | Portfolio, orders, execution | ✅ Complete |
| 5 | Backtesting + analytics | ✅ Complete |
| 7 | Dashboard (Next.js) | ✅ Complete |
| 6 | ML-assisted risk (XGBoost) | Extension |
| 8 | AI Analyst, auth, deployment | Extension |

---

## Quick start

### Docker (everything)

```bash
cp .env.example .env
docker compose up --build
```

- Dashboard — <http://localhost:3000>
- API — <http://localhost:8000>, interactive docs at `/docs`

Migrations run before the API accepts traffic. **No exchange credentials are
required** — the default broker is the paper broker.

If ports 5432, 8000 or 3000 are already taken, set `POSTGRES_HOST_PORT`,
`API_HOST_PORT` or `DASHBOARD_HOST_PORT` in `.env`.

### Seed a demo history

```bash
cd backend
python -m scripts.seed --reset
```

Generates a deterministic 30-day price series and runs the **real** pipeline
over it — the same strategies, risk engine, broker and portfolio the live
system uses. Nothing is fabricated: every order, fill and rejection in the
database was actually produced by the platform.

### Local development

```bash
docker compose up -d db          # Postgres only

cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload

cd ../frontend                   # in a second terminal
npm install
npm run dev
```

---

## Testing

```bash
cd backend
pytest                  # unit tests; no database needed
pytest -m integration   # database round-trip tests; needs Postgres
pytest -m ""            # everything
ruff check app tests
```

The suite includes **architectural tests** that read the import graph and fail
CI if a layering rule is broken:

- `app/domain` may not import SQLAlchemy, FastAPI, brokers or `binance`
- no money field may be annotated as `float`
- no production Binance endpoint may appear anywhere in the source
- `BrokerKind` may not gain a live member

---

## Layout

```
backend/
├── app/
│   ├── core/          config, structured logging, decimal money helpers
│   ├── domain/        pure business models — no I/O, no framework imports
│   ├── strategies/    indicators + four strategies; cannot reach a broker
│   ├── marketdata/    provider protocol: Binance testnet, cache, in-memory
│   ├── risk/          the seven checks and the engine that combines them
│   ├── brokers/       broker protocol: paper (default) and Binance testnet
│   ├── portfolio/     positions and P&L, folded from the fill ledger
│   ├── trading/       the pipeline — the only path from signal to order
│   ├── backtest/      historical replay through the live pipeline
│   ├── analytics/     metrics shared by live trading and backtests
│   ├── services/      use cases wired to persistence
│   ├── db/            SQLAlchemy models, repositories, sessions
│   └── api/           FastAPI routes, schemas, presenters
├── alembic/           migrations
├── scripts/seed.py    deterministic demo history
└── tests/

frontend/
├── app/               ten dashboard sections, one route each
├── components/        UI primitives and charts
└── lib/               typed API client, formatting, data hook
```

`app/domain` and `app/db` are deliberately separate. The domain layer holds
business rules and knows nothing about storage, which is what lets the
backtester run identical logic with no database at all.

---

## Design decisions

**Money is `Decimal`, never `float`.** Binary floating point cannot represent
an exchange tick size such as `0.1` exactly, and the error compounds through a
P&L series. Postgres columns are `NUMERIC(24,10)`; an architectural test fails
the build if a domain field is annotated `float`.

**Quantities round down.** Prices snap to `tick_size` with banker's rounding;
quantities snap to `step_size` toward zero. Rounding a quantity *up* can request
more size than the account can fund, so only the conservative direction is safe.

**Orders are immutable with an explicit state machine.** A status change goes
through `transition_to`, which refuses illegal moves — a `FILLED` order cannot
return to `PENDING` because a retry path ran twice. The new instance is rebuilt
through the constructor rather than copied, because Pydantic's `model_copy`
does not re-run validators.

**Risk decisions carry an enforced invariant.** `REJECT` must approve zero
quantity; `APPROVE` must approve the full amount; `REDUCE` must approve
something strictly between. The model rejects any decision that violates this,
so no later code path can emit a rejection that still carries tradeable size.

**Rejections are persisted.** A `RiskDecision` is stored whether or not it
produced an order, with a per-check breakdown of what was measured against what
was allowed. Reasons are derived from those numbers, not written by hand.

**Idempotency is a database constraint.** Every order carries a
client-generated `client_order_id` with a unique index. Replaying a submission
after a timeout collides at the database rather than creating a second order.

**Positions are a fold over fills.** Fills are the ledger; positions, realised
P&L and every performance metric are derived from them, so there is one source
of truth and no reconciliation step.

**A weighted mean is the wrong aggregator twice.** The risk score blends seven
checks, but two situations bypass it. Categorical limits — daily loss and
drawdown — reject outright, because a good score elsewhere must not average
away an account that should not be trading at all. And a limit breached by more
than 10x rejects outright: a request that far past its cap is more plausibly a
fat finger than an intention, and silently filling 0.3% of it is the dangerous
answer, because the trader may not notice and may simply resubmit.

**Backtests fill at the next bar's open.** A signal computed from the bar
closing at *t* is executed at the open of bar *t+1*, never at *t*'s close —
that price is only knowable once the bar has finished. The loop enforces this
structurally, and a `LookAheadError` assertion fails the run if a future
refactor breaks it.

**The dashboard's charts follow one colour system.** Series identity comes from
a fixed categorical order assigned per entity, so sorting never repaints a
strategy. Status colours (approve / reduce / reject) are reserved, never reused
as a series, and always paired with a label so meaning survives colourblindness
and greyscale.

---

## Configuration

Copy `.env.example` to `.env`. Everything has a working default except exchange
credentials, which are only needed for `BROKER=testnet`.

| Variable | Default | Notes |
|----------|---------|-------|
| `BROKER` | `paper` | `paper` or `testnet` |
| `POSTGRES_*` | see example | Connection parts; the URL is assembled in config |
| `LOG_FORMAT` | `json` | `json` or `console` |
| `POSTGRES_HOST_PORT` | `5432` | Published Docker port; change if 5432 is taken |
| `API_HOST_PORT` | `8000` | Published API port |
| `BINANCE_API_KEY` / `_SECRET` | empty | Only for `BROKER=testnet` |

Testnet keys come from <https://testnet.binancefuture.com>. `.env` is
gitignored; never commit it.

---

## Licence

Educational use.

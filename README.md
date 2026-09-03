# Strategic Trade Analyzer

**Intelligent Trading & Risk Analysis Platform**

A trading platform built around an explicit risk gate. Strategies propose;
they do not execute. Every proposed trade is scored, then approved, resized or
refused with reasons — and the refusals are stored, because "why was this
trade rejected?" is the question the product exists to answer.

> **Simulated trading only.** Real-money execution is not implemented. There is
> no live broker class in this codebase, and `BrokerKind` has no live member —
> so no configuration value can select one.

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

All eight phases are complete. **609 tests passing**, lint and type checks
clean, verified running as a three-container Docker stack.

| Phase | Scope | State |
|-------|-------|-------|
| 0 | Repository audit | ✅ |
| 1 | Foundation, domain models, persistence | ✅ |
| 2 | Market data + strategy engine | ✅ |
| 3 | Risk engine | ✅ |
| 4 | Portfolio, orders, execution | ✅ |
| 5 | Backtesting + analytics | ✅ |
| 6 | ML-assisted risk (XGBoost) | ✅ |
| 7 | Dashboard (Next.js) | ✅ |
| 8 | AI Analyst, auth, deployment | ✅ |

Two items are deliberately deferred and documented in the code rather than
silently left: a process-lifetime broker session (the current one is built per
request — correct for the seed script, wrong for a live trading loop) and
venue reconciliation after an ambiguous submit failure. Both need the
live-trading-loop design that only becomes relevant once real order submission
is wired, and neither is reachable today.

---

## Quick start

### 1. Bring up the stack

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

### 2. Sign in

The dashboard requires authentication. `.env.example` ships with a bootstrap
admin, created on first startup:

```
username: admin
password: change-me-immediately
```

Change it before doing anything else — either set
`BOOTSTRAP_ADMIN_PASSWORD` in `.env` before the first run, or create a proper
account afterwards and stop setting the bootstrap variables:

```bash
curl -X POST http://localhost:8000/api/auth/users \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"username":"you","password":"a-real-password","role":"admin"}'
```

Once a real admin exists, unset `BOOTSTRAP_ADMIN_USERNAME` and
`BOOTSTRAP_ADMIN_PASSWORD`; the bootstrap does nothing when the account it
names already exists.

### 3. Seed a demo history

A fresh database has no trades, so the dashboard opens empty. Run the seeder
inside the API container — no local Python setup needed:

```bash
docker compose exec api python -m scripts.seed --reset
```

This generates a deterministic 30-day price series and runs the **real**
pipeline over it — the same strategies, risk engine, broker and portfolio the
live system uses. Nothing is fabricated: every order, fill and rejection in the
database was actually produced by the platform. Expect about 198 signals,
171 orders and 17 rejections (the split shifts slightly once an ML model is
trained, since the extra check changes some verdicts).

Reload the dashboard and it will be populated.

### 4. Train the adverse-outcome model (optional)

This one is a local-development step: you are meant to read the report before
deciding to save, and a model saved inside a container would not survive a
rebuild.

```bash
cd backend
python -m scripts.train_risk_model --symbol BTCUSDT --save
```

Builds a dataset from stored bars, trains an XGBoost classifier with a
walk-forward split, and prints its out-of-sample AUC and feature importances
**before saving anything** — review the report first; `--save` is a separate
step so a mediocre fit never silently starts influencing live decisions.

Without a saved model the platform runs its seven deterministic checks exactly
as it would if this feature did not exist. This step is entirely optional.

> On the bundled seed data the model scores an AUC of about **0.50**. That is
> the correct answer, not a broken model: the seeded series is a random walk
> with no learnable relationship between the features and the outcome. The same
> pipeline reaches AUC 1.0 on data that does contain a signal — see
> `tests/test_ml_model.py::test_recovers_a_strong_signal_on_separable_data`.

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
pytest -m ""            # everything (609 tests)
ruff check app tests scripts

cd ../frontend
npx tsc --noEmit
```

Alongside the usual unit tests, the suite includes **architectural tests** that
read the import graph and fail CI when a layering rule is broken. These are
what keep the design guarantees from eroding into comments:

| Guarantee | Enforced by |
|---|---|
| The domain layer imports no SQLAlchemy, FastAPI, broker or `binance` | `TestDomainPurity` |
| No money field is annotated `float` | `TestDomainPurity` |
| Strategies cannot reach a broker or construct an `Order` | `TestStrategyIsolation` |
| Only the pipeline turns a signal into an order | `TestSingleExecutionPath` |
| A `RiskDecision` is never authored outside the risk layer | `TestRiskIsMandatory` |
| The ML package cannot reach execution | `TestMLIsolation` |
| The AI Analyst's tool registry holds no write operation | `TestAIAnalystIsolation` |
| `BrokerKind` never gains a live member | `TestNoLiveTrading` |
| No production Binance endpoint appears in the source | `TestNoLiveTrading` |

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
│   ├── ml/            adverse-outcome model: features, labels, dataset, model
│   ├── ai/            AI Analyst: read-only tools + the tool-calling loop
│   ├── auth/          password hashing, JWT, RBAC dependencies
│   ├── services/      use cases wired to persistence
│   ├── db/            SQLAlchemy models, repositories, sessions
│   └── api/           FastAPI routes, schemas, presenters
├── alembic/           migrations
├── scripts/
│   ├── seed.py                deterministic demo history
│   └── train_risk_model.py    trains and saves the adverse-outcome model
└── tests/

frontend/
├── app/
│   ├── login/         sign-in page
│   └── ...            ten dashboard sections, one route each
├── components/        UI primitives and charts
└── lib/               typed API client, auth context, formatting, data hook

models/                trained model files (gitignored; empty by default)
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

**Every size-sensitive check measures the *resulting* position.** Exposure,
leverage and position size are computed from what the book would look like
after the trade, not from the order in isolation — otherwise an order that
*closes* an over-exposed position is scored as if it opened a new one, and the
one trade that should always be allowed through gets refused.

**Idempotency is a database constraint.** Every order carries a
client-generated `client_order_id` with a unique index. Replaying a submission
after a timeout collides at the database rather than creating a second order.

**Positions are a fold over fills.** Fills are the ledger; positions, realised
P&L and every performance metric are derived from them, so there is one source
of truth and no reconciliation step.

**A weighted mean is the wrong aggregator twice.** The risk score blends the
checks, but two situations bypass it. Categorical limits — daily loss and
drawdown — reject outright, because a good score elsewhere must not average
away an account that should not be trading at all. And a limit breached by more
than 10x rejects outright: a request that far past its cap is more plausibly a
fat finger than an intention, and silently filling 0.3% of it is the dangerous
answer, because the trader may not notice and may simply resubmit.

**Daily P&L is mark-to-market, on the simulated clock.** The daily-loss check
measures realised *and* unrealised movement since the day began, so an intraday
loss on an open position can trip the stop before anything is closed. "Today"
follows simulated time during a replay, so the check engages in a backtest
exactly as it would live.

**Backtests fill at the next bar's open.** A signal computed from the bar
closing at *t* is executed at the open of bar *t+1*, never at *t*'s close —
that price is only knowable once the bar has finished. The loop enforces this
structurally, and a `LookAheadError` assertion fails the run if a future
refactor breaks it.

**The ML model assists; it never authorises.** `MLAdverseOutcomeCheck` is one
weighted input among eight, appended to the risk engine only when a trained
model file exists — a fresh checkout has none, so the platform runs identically
to before this feature existed. It cannot reject a trade by itself: only a
hard-check failure or a gross breach can do that. Labels are built with the
triple-barrier method over historical bars — offline only, never in the live or
backtest path, where the outcome is not yet known — and training uses a
walk-forward split, never a random one, so the model is never evaluated on data
from before the period it trained on.

**The AI Analyst has no tool that could act.** Its tool registry
(`app/ai/analyst.py`) holds five read-only functions — the same repositories
the dashboard reads — and nothing that constructs an `Order` or a
`RiskDecision`. "The analyst cannot bypass the risk engine" is therefore a fact
an architecture test can fail on, not a sentence in a system prompt a clever
question could talk it out of.

**The dashboard's charts follow one colour system.** Series identity comes from
a fixed categorical order assigned per entity, so sorting never repaints a
strategy. Status colours (approve / reduce / reject) are reserved, never reused
as a series, and always paired with a label so meaning survives colourblindness
and greyscale.

---

## Security

- **Authentication.** JWT bearer tokens, issued by `POST /api/auth/login`.
  Every route requires one except `/health`, `/ready` and login itself.
- **RBAC.** Three roles, each a strict superset of the one before:

  | Role | Can |
  |---|---|
  | `viewer` | Read the dashboard |
  | `trader` | …and run backtests |
  | `admin` | …and create users, read the audit log |

  Enforced per-router with a single `dependencies=[Depends(require_role(...))]`
  line rather than scattered per-endpoint checks.
- **Rate limiting.** In-memory, no Redis needed at this scale: 10 login
  attempts/minute, 15 AI Analyst questions/hour, 600 requests/hour overall.
- **Audit log.** Every login, failed login and user creation is recorded with
  actor, action and detail, readable at `GET /api/audit` (admin only).
- **Passwords** are bcrypt-hashed — never stored, logged or recoverable.
- **No open self-registration.** Accounts come from an admin or the one-time
  bootstrap, which is the right default for anything that can eventually place
  trades.
- **Production refuses the placeholder secret.** With `APP_ENV=production` and
  the default `JWT_SECRET`, the app will not start — a misconfigured deploy
  fails loudly at boot rather than running with forgeable tokens.

There is deliberately **no** `ALLOW_LIVE_TRADING` flag. A safety switch that
does nothing is worse than none, because it invites trust; the guarantee is
structural instead — there is no live broker to select.

---

## Configuration

Copy `.env.example` to `.env`. Everything has a working default except exchange
credentials (only for `BROKER=testnet`) and the AI Analyst key.

| Variable | Default | Notes |
|----------|---------|-------|
| `BROKER` | `paper` | `paper` or `testnet` — there is no live option |
| `POSTGRES_*` | see example | Connection parts; the URL is assembled in config |
| `LOG_FORMAT` | `json` | `json` or `console` |
| `POSTGRES_HOST_PORT` | `5432` | Published Docker port; change if taken |
| `API_HOST_PORT` | `8000` | Published API port |
| `DASHBOARD_HOST_PORT` | `3000` | Published dashboard port |
| `CORS_ORIGINS` | localhost:3000 | Comma-separated browser origins |
| `JWT_SECRET` | dev placeholder | **Must** be changed for `APP_ENV=production` |
| `JWT_EXPIRY_MINUTES` | `720` | Access token lifetime |
| `BOOTSTRAP_ADMIN_USERNAME` / `_PASSWORD` | see example | First-run admin; unset once real users exist |
| `BINANCE_API_KEY` / `_SECRET` | empty | Only for `BROKER=testnet` |
| `ANTHROPIC_API_KEY` | empty | Enables the AI Analyst; everything else works without it |
| `AI_ANALYST_MODEL` | `claude-opus-5` | Model used for analyst questions |
| `ML_RISK_ENABLED` | `true` | Only engages when a trained model file exists |
| `PUBLIC_API_URL` | `http://localhost:8000` | Baked into the dashboard bundle at **build** time |

Generate a real JWT secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Testnet keys come from <https://testnet.binancefuture.com>. `.env` is
gitignored; never commit it.

---

## Licence

Educational use.

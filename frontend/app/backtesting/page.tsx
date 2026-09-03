"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { money, num, pct, signedPct } from "@/lib/format";
import { BacktestCurve, RejectionReasons } from "@/components/charts";
import { Card, ErrorState, Loading, StatTile } from "@/components/ui";
import { PageHeader } from "@/components/page-header";
import type { BacktestResult } from "@/lib/types";

export default function BacktestingPage() {
  const markets = useApi(() => api.markets());
  const catalogue = useApi(() => api.catalogue());

  const [strategy, setStrategy] = useState("ema_crossover");
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [bars, setBars] = useState(500);

  const [result, setResult] = useState<BacktestResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setRunning(true);
    setError(null);
    try {
      setResult(await api.backtest({ strategy, symbol, interval: "1h", bars }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setResult(null);
    } finally {
      setRunning(false);
    }
  }

  const perf = result?.performance;

  return (
    <>
      <PageHeader
        title="Backtesting"
        description="Replays the same strategy and risk engine the live pipeline uses. A signal from the bar closing at t is filled at the open of bar t+1 — never on its own close."
      />

      <Card title="Configuration" subtitle="Runs against stored history, so the same inputs give the same numbers">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-[11px] uppercase tracking-wider text-muted">Strategy</span>
            <select
              value={strategy}
              onChange={(e) => setStrategy(e.target.value)}
              className="rounded border border-rule bg-surface px-2 py-1.5 text-[13px] text-ink"
            >
              {Object.keys(catalogue.data ?? {}).map((name) => (
                <option key={name} value={name}>{name}</option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-[11px] uppercase tracking-wider text-muted">Symbol</span>
            <select
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              className="rounded border border-rule bg-surface px-2 py-1.5 font-mono text-[13px] text-ink"
            >
              {markets.data?.map((m) => (
                <option key={m.symbol} value={m.symbol}>{m.symbol}</option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-[11px] uppercase tracking-wider text-muted">Bars</span>
            <input
              type="number"
              min={50}
              max={1500}
              value={bars}
              onChange={(e) => setBars(Number(e.target.value))}
              className="w-28 rounded border border-rule bg-surface px-2 py-1.5 tabular text-[13px] text-ink"
            />
          </label>

          <button
            onClick={run}
            disabled={running}
            className="rounded bg-accent px-4 py-1.5 text-[13px] font-medium text-white disabled:opacity-50"
          >
            {running ? "Running…" : "Run backtest"}
          </button>

          {catalogue.data?.[strategy] && (
            <span className="pb-2 text-[11px] text-muted">
              needs at least {catalogue.data[strategy].min_bars + 1} bars
            </span>
          )}
        </div>
      </Card>

      {error && <div className="mt-4"><ErrorState message={error} /></div>}
      {running && <div className="mt-4"><Loading label="Replaying bars" /></div>}

      {result && perf && (
        <>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatTile
              label="Total return"
              value={signedPct(perf.total_return)}
              tone={num(perf.total_return) >= 0 ? "good" : "critical"}
              hint={`${result.bars_processed} bars`}
            />
            <StatTile label="Sharpe ratio" value={num(perf.sharpe_ratio).toFixed(2)} />
            <StatTile
              label="Max drawdown"
              value={pct(perf.max_drawdown)}
              tone={num(perf.max_drawdown) > 0.1 ? "critical" : "neutral"}
            />
            <StatTile
              label="Win rate"
              value={pct(perf.win_rate, 1)}
              hint={`${perf.winning_trades}W / ${perf.losing_trades}L`}
            />
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-[2fr_1fr]">
            <Card
              title={`${result.strategy} · ${result.symbol} · ${result.interval}`}
              subtitle="Equity after each bar"
            >
              <BacktestCurve
                data={result.equity_curve}
                baseline={num(perf.starting_equity)}
                height={300}
              />
            </Card>

            <div className="flex flex-col gap-4">
              <Card title="Run summary">
                <dl className="space-y-2 text-[13px]">
                  {[
                    ["Bars processed", String(result.bars_processed)],
                    ["Signals", String(result.signals)],
                    ["Executed", String(result.executed)],
                    ["Rejected", String(result.rejected)],
                    ["Round trips", String(perf.total_trades)],
                    ["Profit factor", perf.profit_factor ? num(perf.profit_factor).toFixed(2) : "n/a"],
                    ["Expectancy", money(perf.expectancy)],
                    ["Open position P&L", money(result.open_position_pnl)],
                  ].map(([k, v]) => (
                    <div key={k} className="flex justify-between border-b border-rule/60 pb-1.5 last:border-0">
                      <dt className="text-muted">{k}</dt>
                      <dd className="tabular font-medium text-ink">{v}</dd>
                    </div>
                  ))}
                </dl>
              </Card>

              <Card
                title="What refused trades"
                subtitle="Says whether the ideas were poor or the limits never allowed them"
              >
                <RejectionReasons reasons={result.rejection_reasons} />
              </Card>
            </div>
          </div>
        </>
      )}

      {!result && !running && !error && (
        <Card className="mt-4" title="No run yet">
          <p className="text-[13px] text-muted">
            Choose a strategy and symbol above, then run a backtest. Results are
            computed from the stored bar history using the live strategy and risk
            code — not a separate simulation path.
          </p>
        </Card>
      )}
    </>
  );
}

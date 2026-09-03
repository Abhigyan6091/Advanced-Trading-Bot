"use client";

import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { money, num, pct, signedPct } from "@/lib/format";
import { EquityCurve } from "@/components/charts";
import { Card, ErrorState, Loading, StatTile } from "@/components/ui";
import { PageHeader } from "@/components/page-header";

const EXPLAIN: Record<string, string> = {
  sharpe: "Return per unit of total volatility, annualised. A flat curve scores 0, not infinity.",
  sortino: "Sharpe's downside-only counterpart — upside volatility is not treated as risk.",
  calmar: "Total return divided by the worst peak-to-trough decline.",
  profit_factor: "Gross profit over gross loss. Undefined with no losses, so it reads n/a rather than ∞.",
  expectancy: "Average P&L per closed round trip — the figure that decides whether to keep going.",
};

function Metric({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "good" | "critical";
}) {
  return (
    <div className="border-b border-rule/60 py-2.5 last:border-0">
      <div className="flex items-baseline justify-between gap-4">
        <span className="text-[13px] text-ink-2">{label}</span>
        <span
          className={`tabular text-[15px] font-semibold ${
            tone === "good" ? "text-good" : tone === "critical" ? "text-critical" : "text-ink"
          }`}
        >
          {value}
        </span>
      </div>
      {hint && <p className="mt-0.5 max-w-lg text-[11px] leading-snug text-muted">{hint}</p>}
    </div>
  );
}

export default function PerformancePage() {
  const perf = useApi(() => api.performance());
  const curve = useApi(() => api.equityCurve());
  const portfolio = useApi(() => api.portfolio());

  if (perf.error) return <ErrorState message={perf.error} />;
  if (!perf.data) return <Loading label="Computing metrics" />;
  const p = perf.data;

  return (
    <>
      <PageHeader
        title="Performance"
        description="Computed by the same code the backtester uses, so a live Sharpe and a backtested one mean the same thing."
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          label="Total return"
          value={signedPct(p.total_return)}
          tone={num(p.total_return) >= 0 ? "good" : "critical"}
          hint={`${money(p.starting_equity, 0)} → ${money(p.ending_equity, 0)}`}
        />
        <StatTile label="Sharpe ratio" value={num(p.sharpe_ratio).toFixed(2)} hint="annualised" />
        <StatTile
          label="Max drawdown"
          value={pct(p.max_drawdown)}
          tone={num(p.max_drawdown) > 0.1 ? "critical" : "neutral"}
        />
        <StatTile
          label="Win rate"
          value={pct(p.win_rate, 1)}
          hint={`${p.winning_trades}W / ${p.losing_trades}L`}
        />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[2fr_1fr]">
        <Card title="Equity curve">
          {curve.data && portfolio.data ? (
            <EquityCurve
              data={curve.data}
              baseline={num(portfolio.data.starting_balance)}
              height={320}
            />
          ) : (
            <Loading />
          )}
        </Card>

        <Card title="Risk-adjusted returns">
          <Metric label="Sharpe ratio" value={num(p.sharpe_ratio).toFixed(2)} hint={EXPLAIN.sharpe} />
          <Metric label="Sortino ratio" value={num(p.sortino_ratio).toFixed(2)} hint={EXPLAIN.sortino} />
          <Metric
            label="Calmar ratio"
            value={p.calmar_ratio ? num(p.calmar_ratio).toFixed(2) : "n/a"}
            hint={EXPLAIN.calmar}
          />
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card title="Trade statistics">
          <Metric label="Total round trips" value={String(p.total_trades)} />
          <Metric label="Winning trades" value={String(p.winning_trades)} tone="good" />
          <Metric label="Losing trades" value={String(p.losing_trades)} tone="critical" />
          <Metric label="Win rate" value={pct(p.win_rate, 1)} />
          <Metric
            label="Profit factor"
            value={p.profit_factor ? num(p.profit_factor).toFixed(2) : "n/a"}
            hint={EXPLAIN.profit_factor}
          />
        </Card>

        <Card title="Trade economics">
          <Metric label="Expectancy" value={money(p.expectancy)} hint={EXPLAIN.expectancy} />
          <Metric label="Average win" value={money(p.average_win)} tone="good" />
          <Metric label="Average loss" value={money(p.average_loss)} tone="critical" />
          <Metric
            label="Win/loss ratio"
            value={
              num(p.average_loss) > 0
                ? (num(p.average_win) / num(p.average_loss)).toFixed(2)
                : "n/a"
            }
          />
        </Card>
      </div>
    </>
  );
}

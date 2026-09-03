"use client";

import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { money, num, pct } from "@/lib/format";
import { StrategyPnl, seriesColor } from "@/components/charts";
import { Card, Cell, ErrorState, Loading, PnL, Row, StatTile, Table } from "@/components/ui";
import { PageHeader } from "@/components/page-header";

const DESCRIPTIONS: Record<string, string> = {
  ema_crossover:
    "Trend following. Fires on the bar where the fast EMA crosses the slow one — a cross is an event, not a state, so it does not re-fire through a trend.",
  rsi: "Momentum reversion. Waits for RSI to exit an extreme rather than entering at it, so it never catches a falling knife.",
  macd: "Momentum of momentum. Trades the histogram changing sign as the MACD line crosses its own signal line.",
  mean_reversion:
    "Fades displacement from a rolling mean, measured in standard deviations. Deliberately the opposite stance to the trend strategies.",
};

export default function StrategiesPage() {
  const strategies = useApi(() => api.strategies());

  if (strategies.error) return <ErrorState message={strategies.error} />;
  if (!strategies.data) return <Loading label="Loading strategies" />;

  const data = strategies.data;
  // Colour follows the entity: the registry order fixes each strategy's hue,
  // so sorting the table never repaints the chart.
  const order = data.map((s) => s.name);
  const totalSignals = data.reduce((a, s) => a + s.signals, 0);
  const totalPnl = data.reduce((a, s) => a + num(s.realized_pnl), 0);
  const best = [...data].sort((a, b) => num(b.realized_pnl) - num(a.realized_pnl))[0];

  return (
    <>
      <PageHeader
        title="Strategies"
        description="Each strategy is a pure function from a bar window to a proposal. None of them can place an order — that is the risk engine's decision."
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile label="Registered" value={String(data.length)} />
        <StatTile label="Signals generated" value={String(totalSignals)} />
        <StatTile
          label="Combined realised P&L"
          value={money(totalPnl)}
          tone={totalPnl >= 0 ? "good" : "critical"}
        />
        <StatTile
          label="Best performer"
          value={best?.name ?? "—"}
          hint={best ? money(best.realized_pnl) : undefined}
        />
      </div>

      <Card
        className="mt-4"
        title="Realised P&L by strategy"
        subtitle="Attributed through the signal → order → fill chain each order records"
      >
        <StrategyPnl data={data} order={order} />
        {/* The table is the relief for light-mode series colours below 3:1,
            and the accessible alternative to reading values off the bars. */}
        <div className="mt-4 border-t border-rule pt-3">
          <Table head={["Strategy", "Signals", "Actionable", "Approved", "Reduced", "Rejected", "Realised P&L"]}>
            {data.map((s) => (
              <Row key={s.name}>
                <Cell>
                  <span className="flex items-center gap-2">
                    <span
                      className="inline-block h-2.5 w-2.5 rounded-sm"
                      style={{ background: seriesColor(s.name, order) }}
                      aria-hidden="true"
                    />
                    {s.name}
                  </span>
                </Cell>
                <Cell mono align="right">{s.signals}</Cell>
                <Cell mono align="right">{s.actionable}</Cell>
                <Cell mono align="right" className="text-good">{s.approved}</Cell>
                <Cell mono align="right" className="text-[color:var(--warning)]">{s.reduced}</Cell>
                <Cell mono align="right" className="text-critical">{s.rejected}</Cell>
                <Cell align="right"><PnL value={s.realized_pnl} /></Cell>
              </Row>
            ))}
          </Table>
        </div>
      </Card>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        {data.map((s) => {
          const decisions = s.approved + s.reduced + s.rejected;
          return (
            <Card key={s.name} title={s.name} subtitle={DESCRIPTIONS[s.name]}>
              <div className="mb-3 flex flex-wrap gap-1.5">
                {Object.entries(s.parameters).map(([k, v]) => (
                  <span
                    key={k}
                    className="rounded border border-rule bg-sunken px-1.5 py-0.5 font-mono text-[11px] text-ink-2"
                  >
                    {k}={String(v)}
                  </span>
                ))}
              </div>
              <dl className="grid grid-cols-3 gap-3 text-[13px]">
                <div>
                  <dt className="text-[11px] uppercase tracking-wider text-muted">Signals</dt>
                  <dd className="tabular mt-0.5 font-semibold text-ink">{s.signals}</dd>
                </div>
                <div>
                  <dt className="text-[11px] uppercase tracking-wider text-muted">Approval rate</dt>
                  <dd className="tabular mt-0.5 font-semibold text-ink">
                    {decisions ? pct(s.approved / decisions, 0) : "—"}
                  </dd>
                </div>
                <div>
                  <dt className="text-[11px] uppercase tracking-wider text-muted">Realised</dt>
                  <dd className="mt-0.5 font-semibold"><PnL value={s.realized_pnl} /></dd>
                </div>
              </dl>
            </Card>
          );
        })}
      </div>
    </>
  );
}

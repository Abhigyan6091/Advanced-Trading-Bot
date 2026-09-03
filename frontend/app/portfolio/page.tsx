"use client";

import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { money, num, pct, qty, signedPct, time } from "@/lib/format";
import { AllocationBars, EquityCurve } from "@/components/charts";
import {
  Badge,
  Card,
  Cell,
  ErrorState,
  Loading,
  PnL,
  Row,
  SideBadge,
  StatTile,
  Table,
} from "@/components/ui";
import { PageHeader } from "@/components/page-header";

export default function PortfolioPage() {
  const portfolio = useApi(() => api.portfolio());
  const curve = useApi(() => api.equityCurve());
  const allocation = useApi(() => api.allocation());
  const fills = useApi(() => api.fills(25));

  if (portfolio.error) return <ErrorState message={portfolio.error} />;
  if (!portfolio.data) return <Loading label="Loading portfolio" />;
  const p = portfolio.data;

  const symbolOrder = p.positions.map((x) => x.symbol);

  return (
    <>
      <PageHeader
        title="Portfolio"
        description="Balances, exposure and P&L, all derived from the fill ledger rather than stored as separate counters."
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile label="Equity" value={money(p.equity)} delta={p.total_return} deltaLabel={signedPct(p.total_return)} />
        <StatTile label="Cash" value={money(p.cash)} hint={`${money(p.position_value)} in positions`} />
        <StatTile label="Realised P&L" value={money(p.realized_pnl)} tone={num(p.realized_pnl) >= 0 ? "good" : "critical"} />
        <StatTile label="Unrealised P&L" value={money(p.unrealized_pnl)} tone={num(p.unrealized_pnl) >= 0 ? "good" : "critical"} />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[2fr_1fr]">
        <Card title="Equity curve" subtitle="Marked after every fill">
          {curve.data ? (
            <EquityCurve data={curve.data} baseline={num(p.starting_balance)} height={300} />
          ) : (
            <Loading />
          )}
        </Card>

        <div className="flex flex-col gap-4">
          <Card title="Exposure by symbol" subtitle="Share of gross exposure">
            {allocation.data ? (
              <AllocationBars allocation={allocation.data} order={symbolOrder} />
            ) : (
              <Loading />
            )}
          </Card>

          <Card title="Account">
            <dl className="space-y-2 text-[13px]">
              {[
                ["Starting balance", money(p.starting_balance)],
                ["Peak equity", money(p.peak_equity)],
                ["Drawdown", pct(p.drawdown)],
                ["Gross exposure", money(p.gross_exposure)],
                ["Leverage", `${num(p.leverage).toFixed(2)}x`],
                ["Commission paid", money(p.total_commission)],
              ].map(([k, v]) => (
                <div key={k} className="flex justify-between border-b border-rule/60 pb-1.5 last:border-0">
                  <dt className="text-muted">{k}</dt>
                  <dd className="tabular font-medium text-ink">{v}</dd>
                </div>
              ))}
            </dl>
          </Card>
        </div>
      </div>

      <Card className="mt-4" title="Positions" subtitle={`${p.open_position_count} open`}>
        <Table
          head={["Symbol", "Side", "Quantity", "Avg entry", "Mark", "Notional", "Unrealised", "Realised"]}
          empty={!p.positions.length}
        >
          {p.positions.map((pos) => (
            <Row key={pos.symbol}>
              <Cell mono>{pos.symbol}</Cell>
              <Cell><Badge tone={pos.side === "LONG" ? "good" : "critical"}>{pos.side}</Badge></Cell>
              <Cell mono align="right">{qty(pos.quantity)}</Cell>
              <Cell mono align="right">{money(pos.average_entry_price)}</Cell>
              <Cell mono align="right">{pos.mark_price ? money(pos.mark_price) : "—"}</Cell>
              <Cell mono align="right">{pos.notional ? money(pos.notional) : "—"}</Cell>
              <Cell align="right">{pos.unrealized_pnl ? <PnL value={pos.unrealized_pnl} /> : "—"}</Cell>
              <Cell align="right"><PnL value={pos.realized_pnl} /></Cell>
            </Row>
          ))}
        </Table>
      </Card>

      <Card className="mt-4" title="Recent fills" subtitle="The ledger every figure above is derived from">
        {fills.data ? (
          <Table head={["Time", "Symbol", "Side", "Quantity", "Price", "Commission"]} empty={!fills.data.length}>
            {fills.data.map((f) => (
              <Row key={f.id}>
                <Cell mono>{time(f.executed_at)}</Cell>
                <Cell mono>{f.symbol}</Cell>
                <Cell><SideBadge side={f.side} /></Cell>
                <Cell mono align="right">{qty(f.quantity)}</Cell>
                <Cell mono align="right">{money(f.price)}</Cell>
                <Cell mono align="right">{money(f.commission, 4)}</Cell>
              </Row>
            ))}
          </Table>
        ) : (
          <Loading />
        )}
      </Card>
    </>
  );
}

"use client";

import Link from "next/link";
import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { money, num, pct, qty, signedPct, time } from "@/lib/format";
import { EquityCurve, VerdictBars } from "@/components/charts";
import {
  Badge,
  Card,
  Cell,
  ErrorState,
  Loading,
  PnL,
  RiskMeter,
  Row,
  SideBadge,
  StatTile,
  Table,
  VerdictBadge,
} from "@/components/ui";
import { PageHeader } from "@/components/page-header";

export default function OverviewPage() {
  const overview = useApi(() => api.overview());
  const curve = useApi(() => api.equityCurve());
  const risk = useApi(() => api.riskSummary());
  const orders = useApi(() => api.orders(6));

  if (overview.error) return <ErrorState message={overview.error} />;
  if (!overview.data) return <Loading label="Loading portfolio" />;

  const p = overview.data.portfolio;

  return (
    <>
      <PageHeader
        title="Overview"
        description="Portfolio, risk posture and recent activity across every strategy."
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          label="Portfolio value"
          value={money(p.equity)}
          delta={p.total_return}
          deltaLabel={signedPct(p.total_return)}
          hint="since inception"
        />
        <StatTile
          label="Total P&L"
          value={money(p.total_pnl)}
          tone={num(p.total_pnl) >= 0 ? "good" : "critical"}
          hint={`${money(p.realized_pnl)} realised`}
        />
        <StatTile
          label="Gross exposure"
          value={money(p.gross_exposure)}
          hint={`${num(p.leverage).toFixed(2)}x leverage`}
        />
        <StatTile
          label="Max drawdown"
          value={pct(p.drawdown)}
          tone={num(p.drawdown) > 0.1 ? "critical" : "neutral"}
          hint={`peak ${money(p.peak_equity, 0)}`}
        />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[2fr_1fr]">
        <Card
          title="Equity curve"
          subtitle="Rebuilt by replaying the fill ledger, so it cannot disagree with the trades"
        >
          {curve.error ? (
            <ErrorState message={curve.error} />
          ) : curve.data ? (
            <EquityCurve data={curve.data} baseline={num(p.starting_balance)} />
          ) : (
            <Loading />
          )}
        </Card>

        <div className="flex flex-col gap-4">
          <Card title="Risk posture" subtitle="Mean score of the last 20 decisions">
            <RiskMeter score={num(overview.data.risk_score)} />
            <div className="mt-4 border-t border-rule pt-3">
              {risk.data ? (
                <VerdictBars counts={risk.data.decision_counts} />
              ) : (
                <Loading />
              )}
            </div>
          </Card>

          <Card title="Today">
            <dl className="grid grid-cols-2 gap-3 text-[13px]">
              <div>
                <dt className="text-[11px] uppercase tracking-wider text-muted">Signals</dt>
                <dd className="tabular mt-0.5 text-lg font-semibold text-ink">
                  {overview.data.signals_today}
                </dd>
              </div>
              <div>
                <dt className="text-[11px] uppercase tracking-wider text-muted">Rejected</dt>
                <dd className="tabular mt-0.5 text-lg font-semibold text-critical">
                  {overview.data.rejected_today}
                </dd>
              </div>
              <div>
                <dt className="text-[11px] uppercase tracking-wider text-muted">Open orders</dt>
                <dd className="tabular mt-0.5 text-lg font-semibold text-ink">
                  {overview.data.open_orders}
                </dd>
              </div>
              <div>
                <dt className="text-[11px] uppercase tracking-wider text-muted">Day P&L</dt>
                <dd className="mt-0.5 text-lg font-semibold">
                  <PnL value={p.daily_pnl} />
                </dd>
              </div>
            </dl>
          </Card>
        </div>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card
          title="Open positions"
          subtitle={`${p.open_position_count} held`}
          action={
            <Link href="/portfolio" className="text-[12px] text-accent hover:underline">
              View all
            </Link>
          }
        >
          <Table head={["Symbol", "Side", "Qty", "Entry", "Mark", "Unrealised"]} empty={!p.positions.length}>
            {p.positions.map((pos) => (
              <Row key={pos.symbol}>
                <Cell mono>{pos.symbol}</Cell>
                <Cell>
                  <Badge tone={pos.side === "LONG" ? "good" : "critical"}>{pos.side}</Badge>
                </Cell>
                <Cell mono align="right">{qty(pos.quantity)}</Cell>
                <Cell mono align="right">{money(pos.average_entry_price)}</Cell>
                <Cell mono align="right">{pos.mark_price ? money(pos.mark_price) : "—"}</Cell>
                <Cell align="right">
                  {pos.unrealized_pnl ? <PnL value={pos.unrealized_pnl} /> : "—"}
                </Cell>
              </Row>
            ))}
          </Table>
        </Card>

        <Card
          title="Recent orders"
          action={
            <Link href="/orders" className="text-[12px] text-accent hover:underline">
              View all
            </Link>
          }
        >
          {orders.error ? (
            <ErrorState message={orders.error} />
          ) : (
            <Table head={["Time", "Symbol", "Side", "Qty", "Fill", "Status"]} empty={!orders.data?.length}>
              {orders.data?.map((o) => (
                <Row key={o.id}>
                  <Cell mono>{time(o.created_at)}</Cell>
                  <Cell mono>{o.symbol}</Cell>
                  <Cell><SideBadge side={o.side} /></Cell>
                  <Cell mono align="right">{qty(o.quantity)}</Cell>
                  <Cell mono align="right">
                    {o.average_fill_price ? money(o.average_fill_price) : "—"}
                  </Cell>
                  <Cell>
                    <Badge tone={o.status === "FILLED" ? "good" : "neutral"}>{o.status}</Badge>
                  </Cell>
                </Row>
              ))}
            </Table>
          )}
        </Card>
      </div>

      <Card
        className="mt-4"
        title="Rejected trades"
        subtitle="Every refusal is stored with the numbers behind it — this is the record the AI Analyst reads"
        action={
          <Link href="/risk" className="text-[12px] text-accent hover:underline">
            Risk detail
          </Link>
        }
      >
        {risk.data ? (
          <Table head={["Time", "Symbol", "Strategy", "Verdict", "Score", "Reasons"]}
            empty={!risk.data.recent.filter((d) => d.action === "REJECT").length}>
            {risk.data.recent
              .filter((d) => d.action === "REJECT")
              .slice(0, 5)
              .map((d) => (
                <Row key={d.id}>
                  <Cell mono>{time(d.created_at)}</Cell>
                  <Cell mono>{d.symbol ?? "—"}</Cell>
                  <Cell>{d.strategy ?? "—"}</Cell>
                  <Cell><VerdictBadge action={d.action} /></Cell>
                  <Cell mono align="right">{num(d.score).toFixed(0)}</Cell>
                  <Cell className="text-[12px] text-ink-2">
                    {d.reasons.length ? d.reasons.join(" · ") : "—"}
                  </Cell>
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

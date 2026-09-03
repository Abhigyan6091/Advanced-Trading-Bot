"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { money, num, qty, time } from "@/lib/format";
import {
  Badge,
  Card,
  Cell,
  ErrorState,
  Loading,
  Row,
  SideBadge,
  StatTile,
  Table,
} from "@/components/ui";
import { PageHeader } from "@/components/page-header";

const STATUS_TONE: Record<string, "good" | "neutral" | "critical" | "warning"> = {
  FILLED: "good",
  PARTIALLY_FILLED: "warning",
  SUBMITTED: "neutral",
  PENDING: "neutral",
  CANCELLED: "neutral",
  REJECTED: "critical",
  EXPIRED: "critical",
};

export default function OrdersPage() {
  const [tab, setTab] = useState<"orders" | "signals">("orders");
  const orders = useApi(() => api.orders(80));
  const stats = useApi(() => api.orderStats());
  const signals = useApi(() => api.signals(80));

  return (
    <>
      <PageHeader
        title="Orders"
        description="Orders and the signals that produced them. Every order carries a client order ID — the idempotency key that stops a retry opening a second position."
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile label="Total orders" value={String(orders.data?.length ?? 0)} hint="most recent 80" />
        <StatTile label="Filled" value={String(stats.data?.FILLED ?? 0)} tone="good" />
        <StatTile
          label="Working"
          value={String((stats.data?.SUBMITTED ?? 0) + (stats.data?.PENDING ?? 0))}
        />
        <StatTile label="Signals" value={String(signals.data?.length ?? 0)} hint="includes HOLDs" />
      </div>

      <Card
        className="mt-4"
        title={tab === "orders" ? "Order blotter" : "Signal log"}
        subtitle={
          tab === "orders"
            ? "Each row links back to the risk decision that authorised it"
            : "Every signal is stored, including HOLDs — a strategy cannot be judged on its trades alone"
        }
        action={
          <div className="flex gap-1">
            {(["orders", "signals"] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`rounded border px-2 py-1 text-[11px] capitalize ${
                  tab === t
                    ? "border-accent bg-accent-soft text-accent"
                    : "border-rule text-ink-2 hover:bg-sunken"
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        }
      >
        {tab === "orders" ? (
          orders.error ? (
            <ErrorState message={orders.error} />
          ) : orders.data ? (
            <Table
              head={["Time", "Client order ID", "Symbol", "Side", "Type", "Qty", "Filled", "Avg price", "Status", "Risk"]}
              empty={!orders.data.length}
            >
              {orders.data.map((o) => (
                <Row key={o.id}>
                  <Cell mono>{time(o.created_at)}</Cell>
                  <Cell mono className="text-muted">{o.client_order_id.slice(0, 16)}…</Cell>
                  <Cell mono>{o.symbol}</Cell>
                  <Cell><SideBadge side={o.side} /></Cell>
                  <Cell className="text-[12px] text-ink-2">{o.order_type}</Cell>
                  <Cell mono align="right">{qty(o.quantity)}</Cell>
                  <Cell mono align="right">{qty(o.filled_quantity)}</Cell>
                  <Cell mono align="right">
                    {o.average_fill_price ? money(o.average_fill_price) : "—"}
                  </Cell>
                  <Cell>
                    <Badge tone={STATUS_TONE[o.status] ?? "neutral"}>{o.status}</Badge>
                  </Cell>
                  <Cell>
                    {o.risk_decision_id ? (
                      <span className="text-[11px] text-accent">linked</span>
                    ) : (
                      <span className="text-[11px] text-muted">—</span>
                    )}
                  </Cell>
                </Row>
              ))}
            </Table>
          ) : (
            <Loading />
          )
        ) : signals.error ? (
          <ErrorState message={signals.error} />
        ) : signals.data ? (
          <Table
            head={["Time", "Strategy", "Symbol", "Action", "Strength", "Reference price", "Bar close"]}
            empty={!signals.data.length}
          >
            {signals.data.map((s) => (
              <Row key={s.id}>
                <Cell mono>{time(s.created_at)}</Cell>
                <Cell>{s.strategy}</Cell>
                <Cell mono>{s.symbol}</Cell>
                <Cell>
                  {s.action === "HOLD" ? (
                    <Badge>HOLD</Badge>
                  ) : (
                    <SideBadge side={s.action} />
                  )}
                </Cell>
                <Cell mono align="right">{num(s.strength).toFixed(2)}</Cell>
                <Cell mono align="right">{money(s.reference_price)}</Cell>
                <Cell mono className="text-muted">{time(s.bar_close_time)}</Cell>
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

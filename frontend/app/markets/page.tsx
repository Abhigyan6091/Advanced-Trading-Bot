"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { money, num, qty, signedPct } from "@/lib/format";
import { PriceChart } from "@/components/charts";
import { Card, Cell, ErrorState, Loading, Row, Table } from "@/components/ui";
import { PageHeader } from "@/components/page-header";

export default function MarketsPage() {
  const markets = useApi(() => api.markets());
  const [symbol, setSymbol] = useState("BTCUSDT");
  const bars = useApi(() => api.bars(symbol, "1h", 240), [symbol]);

  if (markets.error) return <ErrorState message={markets.error} />;

  return (
    <>
      <PageHeader
        title="Markets"
        description="Instruments and their exchange trading rules. Every order is snapped to these before submission."
      />

      <Card
        title={`${symbol} · 1h`}
        subtitle="Closed candles only — a bar still forming is never shown"
        action={
          <div className="flex gap-1">
            {markets.data?.map((m) => (
              <button
                key={m.symbol}
                onClick={() => setSymbol(m.symbol)}
                className={`rounded border px-2 py-1 font-mono text-[11px] ${
                  symbol === m.symbol
                    ? "border-accent bg-accent-soft text-accent"
                    : "border-rule text-ink-2 hover:bg-sunken"
                }`}
              >
                {m.symbol}
              </button>
            ))}
          </div>
        }
      >
        {bars.error ? (
          <ErrorState message={bars.error} />
        ) : bars.data ? (
          <PriceChart bars={bars.data} />
        ) : (
          <Loading />
        )}
      </Card>

      <Card className="mt-4" title="Instruments" subtitle="Venue constraints, refreshed from the exchange">
        {markets.data ? (
          <Table
            head={["Symbol", "Last", "24h", "Tick size", "Step size", "Min qty", "Min notional", "Max lev"]}
            empty={!markets.data.length}
          >
            {markets.data.map((m) => (
              <Row key={m.symbol}>
                <Cell mono>{m.symbol}</Cell>
                <Cell mono align="right">{m.last_price ? money(m.last_price) : "—"}</Cell>
                <Cell align="right">
                  {m.change_24h !== null ? (
                    <span
                      className={`tabular font-medium ${
                        num(m.change_24h) >= 0 ? "text-good" : "text-critical"
                      }`}
                    >
                      {signedPct(m.change_24h)}
                    </span>
                  ) : (
                    "—"
                  )}
                </Cell>
                <Cell mono align="right">{qty(m.tick_size, 8)}</Cell>
                <Cell mono align="right">{qty(m.step_size, 8)}</Cell>
                <Cell mono align="right">{qty(m.min_quantity, 8)}</Cell>
                <Cell mono align="right">{money(m.min_notional, 0)}</Cell>
                <Cell mono align="right">{m.max_leverage}x</Cell>
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

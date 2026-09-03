"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { money, num, qty } from "@/lib/format";
import { Badge, Card, ErrorState, Loading } from "@/components/ui";
import { PageHeader } from "@/components/page-header";

/**
 * Order ticket.
 *
 * Deliberately a preview rather than a submit button: manual order entry is a
 * write path that has to go through the risk engine and an authenticated
 * session, and authentication arrives in Phase 8. Showing the ticket with its
 * venue constraints and a computed notional is honest about what exists;
 * wiring a button that bypassed risk would not be.
 */
export default function TradePage() {
  const markets = useApi(() => api.markets());
  const portfolio = useApi(() => api.portfolio());

  const [symbol, setSymbol] = useState("BTCUSDT");
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [quantity, setQuantity] = useState("0.01");

  if (markets.error) return <ErrorState message={markets.error} />;
  if (!markets.data) return <Loading label="Loading instruments" />;

  const instrument = markets.data.find((m) => m.symbol === symbol);
  const price = instrument?.last_price ? num(instrument.last_price) : 0;
  const notional = num(quantity) * price;
  const equity = portfolio.data ? num(portfolio.data.equity) : 0;
  const positionPct = equity ? notional / equity : 0;

  const belowMinQty = instrument ? num(quantity) < num(instrument.min_quantity) : false;
  const belowMinNotional = instrument ? notional < num(instrument.min_notional) : false;

  return (
    <>
      <PageHeader
        title="Trade"
        description="Build an order ticket and see how it would be assessed. Orders reach the venue only through the pipeline, and only with a risk decision that permits them."
      />

      <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
        <Card title="Order ticket">
          <div className="space-y-3">
            <label className="flex flex-col gap-1">
              <span className="text-[11px] uppercase tracking-wider text-muted">Symbol</span>
              <select
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
                className="rounded border border-rule bg-surface px-2 py-1.5 font-mono text-[13px] text-ink"
              >
                {markets.data.map((m) => (
                  <option key={m.symbol} value={m.symbol}>{m.symbol}</option>
                ))}
              </select>
            </label>

            <div className="flex flex-col gap-1">
              <span className="text-[11px] uppercase tracking-wider text-muted">Side</span>
              <div className="flex gap-2">
                {(["BUY", "SELL"] as const).map((s) => (
                  <button
                    key={s}
                    onClick={() => setSide(s)}
                    className={`flex-1 rounded border px-3 py-1.5 text-[13px] font-medium ${
                      side === s
                        ? s === "BUY"
                          ? "border-good bg-[var(--good-bg)] text-good"
                          : "border-critical bg-[var(--critical-bg)] text-critical"
                        : "border-rule text-ink-2 hover:bg-sunken"
                    }`}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>

            <label className="flex flex-col gap-1">
              <span className="text-[11px] uppercase tracking-wider text-muted">Quantity</span>
              <input
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
                className="rounded border border-rule bg-surface px-2 py-1.5 tabular text-[13px] text-ink"
              />
            </label>

            <div className="rounded border border-rule bg-sunken px-3 py-2.5 text-[12px]">
              <p className="mb-1 text-[10px] uppercase tracking-wider text-muted">
                Venue constraints
              </p>
              {instrument && (
                <dl className="space-y-1">
                  <div className="flex justify-between">
                    <dt className="text-muted">Step size</dt>
                    <dd className="tabular font-mono">{qty(instrument.step_size, 8)}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-muted">Min quantity</dt>
                    <dd className={`tabular font-mono ${belowMinQty ? "text-critical" : ""}`}>
                      {qty(instrument.min_quantity, 8)}
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-muted">Min notional</dt>
                    <dd className={`tabular font-mono ${belowMinNotional ? "text-critical" : ""}`}>
                      {money(instrument.min_notional, 0)}
                    </dd>
                  </div>
                </dl>
              )}
            </div>
          </div>
        </Card>

        <Card title="How this would be assessed" subtitle="Preview only — nothing is submitted">
          <dl className="space-y-2 text-[13px]">
            {[
              ["Last price", price ? money(price) : "—"],
              ["Order notional", money(notional)],
              ["Share of equity", `${(positionPct * 100).toFixed(2)}%`],
              ["Account equity", money(equity)],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between border-b border-rule/60 pb-1.5">
                <dt className="text-muted">{k}</dt>
                <dd className="tabular font-medium text-ink">{v}</dd>
              </div>
            ))}
          </dl>

          <div className="mt-4 space-y-2">
            {belowMinQty && (
              <p className="text-[12px] text-critical">
                ✕ Below the venue minimum quantity — the exchange would refuse this.
              </p>
            )}
            {belowMinNotional && (
              <p className="text-[12px] text-critical">
                ✕ Below the venue minimum notional of {money(instrument!.min_notional, 0)}.
              </p>
            )}
            {positionPct > 0.1 && (
              <p className="text-[12px] text-[color:var(--warning)]">
                ◐ {(positionPct * 100).toFixed(1)}% of equity exceeds the 10% position
                cap — the risk engine would size this down.
              </p>
            )}
            {!belowMinQty && !belowMinNotional && positionPct <= 0.1 && positionPct > 0 && (
              <p className="text-[12px] text-good">
                ✓ Within the position-size limit. The remaining checks — exposure,
                leverage, daily loss, drawdown, volatility and order value — are
                evaluated at submission.
              </p>
            )}
          </div>

          <div className="mt-4 rounded border border-rule bg-sunken px-3 py-2.5">
            <div className="mb-1.5 flex items-center gap-2">
              <Badge tone="accent">Phase 8</Badge>
              <span className="text-[12px] font-medium text-ink">Submission is not wired</span>
            </div>
            <p className="text-[12px] leading-snug text-muted">
              Manual entry is a write path, so it needs an authenticated session and
              an audited actor. Authentication arrives with the security phase. Until
              then orders are created only by strategies running through the
              pipeline — where the risk engine cannot be skipped.
            </p>
          </div>
        </Card>
      </div>
    </>
  );
}

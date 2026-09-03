"use client";

import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { money, num, time } from "@/lib/format";
import { Badge, Card, ErrorState, Loading } from "@/components/ui";
import { PageHeader } from "@/components/page-header";

/**
 * AI Analyst.
 *
 * The analyst itself lands in Phase 8. What this page shows now is the data it
 * will read and the tools it will be given — deliberately all read-only. It has
 * no order-placing tool, so "the analyst cannot bypass the risk engine" is a
 * property of its tool registry rather than a promise in a prompt.
 */

const TOOLS = [
  {
    name: "get_portfolio",
    description: "Balances, positions, exposure and P&L as of now.",
    answers: "Why did my portfolio lose money today?",
  },
  {
    name: "get_risk_decision",
    description: "One decision with its full check breakdown: observed value, limit and reason.",
    answers: "Why was my BTC trade rejected?",
  },
  {
    name: "get_strategy_performance",
    description: "Per-strategy signals, verdict mix and attributed P&L.",
    answers: "Which strategy performed best?",
  },
  {
    name: "get_trades",
    description: "Order and fill history, filterable by symbol and period.",
    answers: "What did I trade this week?",
  },
  {
    name: "get_positions",
    description: "Open positions with notional, leverage contribution and unrealised P&L.",
    answers: "What are my riskiest positions?",
  },
];

export default function AiAnalystPage() {
  const rejections = useApi(() => api.rejections(3));
  const portfolio = useApi(() => api.portfolio());

  return (
    <>
      <PageHeader
        title="AI Analyst"
        description="A read-only assistant over the platform's own records. It answers from stored decisions rather than inference."
      />

      <Card
        title="Not yet enabled"
        subtitle="Scheduled for Phase 8, alongside authentication and audit logging"
      >
        <div className="flex items-start gap-3">
          <Badge tone="accent">Phase 8</Badge>
          <p className="max-w-2xl text-[13px] leading-relaxed text-ink-2">
            The analyst will use tool calling against the endpoints this dashboard
            already consumes. Its tool registry contains <strong>no write
            operation</strong> — no order placement, no limit changes, no
            cancellation. That is what makes &ldquo;the analyst cannot bypass the
            risk engine&rdquo; a structural property rather than an instruction it
            could be talked out of. A test asserts the registry stays read-only.
          </p>
        </div>
      </Card>

      <Card
        className="mt-4"
        title="Planned tools"
        subtitle="Read-only, one per question the analyst is meant to answer"
      >
        <ul className="space-y-3">
          {TOOLS.map((t) => (
            <li key={t.name} className="border-b border-rule/60 pb-3 last:border-0 last:pb-0">
              <div className="flex flex-wrap items-baseline gap-2">
                <code className="rounded border border-rule bg-sunken px-1.5 py-0.5 font-mono text-[12px] text-accent">
                  {t.name}
                </code>
                <span className="text-[12px] text-muted">{t.description}</span>
              </div>
              <p className="mt-1 text-[12px] text-ink-2">
                <span className="text-muted">Answers: </span>
                &ldquo;{t.answers}&rdquo;
              </p>
            </li>
          ))}
        </ul>
      </Card>

      <Card
        className="mt-4"
        title="The data it will read"
        subtitle="Already stored — these are real records from this account"
      >
        {rejections.error ? (
          <ErrorState message={rejections.error} />
        ) : rejections.data && portfolio.data ? (
          <div className="space-y-4">
            <div className="rounded border border-rule bg-sunken px-3 py-2.5">
              <p className="mb-1 text-[11px] uppercase tracking-wider text-muted">
                Example: &ldquo;Why was my last trade rejected?&rdquo;
              </p>
              {rejections.data.length ? (
                <div className="text-[13px] text-ink-2">
                  <p>
                    The most recent rejection was{" "}
                    <span className="font-mono text-ink">
                      {rejections.data[0].symbol}
                    </span>{" "}
                    from{" "}
                    <span className="font-medium text-ink">
                      {rejections.data[0].strategy}
                    </span>{" "}
                    at {time(rejections.data[0].created_at)}, scoring{" "}
                    <span className="tabular font-medium text-ink">
                      {num(rejections.data[0].score).toFixed(0)}
                    </span>
                    .
                  </p>
                  <ul className="mt-2 space-y-1">
                    {rejections.data[0].reasons.map((r) => (
                      <li key={r} className="text-critical">— {r}</li>
                    ))}
                  </ul>
                  <p className="mt-2 text-[12px] text-muted">
                    Every number in that answer comes from a stored risk decision.
                    The analyst will not need to infer any of it.
                  </p>
                </div>
              ) : (
                <p className="text-[13px] text-muted">
                  No rejections recorded yet.
                </p>
              )}
            </div>

            <div className="rounded border border-rule bg-sunken px-3 py-2.5">
              <p className="mb-1 text-[11px] uppercase tracking-wider text-muted">
                Example: &ldquo;What are my riskiest positions?&rdquo;
              </p>
              {portfolio.data.positions.length ? (
                <ul className="space-y-1 text-[13px] text-ink-2">
                  {[...portfolio.data.positions]
                    .sort((a, b) => num(b.notional) - num(a.notional))
                    .map((p) => (
                      <li key={p.symbol} className="flex justify-between">
                        <span className="font-mono">{p.symbol}</span>
                        <span className="tabular">
                          {money(p.notional)} notional ·{" "}
                          {((num(p.notional) / num(portfolio.data!.equity)) * 100).toFixed(1)}%
                          of equity
                        </span>
                      </li>
                    ))}
                </ul>
              ) : (
                <p className="text-[13px] text-muted">No open positions.</p>
              )}
            </div>
          </div>
        ) : (
          <Loading />
        )}
      </Card>
    </>
  );
}

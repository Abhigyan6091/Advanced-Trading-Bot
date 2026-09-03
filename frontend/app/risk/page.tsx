"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { money, num, pct, time } from "@/lib/format";
import { RejectionReasons, VerdictBars } from "@/components/charts";
import {
  Card,
  Cell,
  ErrorState,
  Loading,
  RiskMeter,
  Row,
  StatTile,
  Table,
  VerdictBadge,
} from "@/components/ui";
import { PageHeader } from "@/components/page-header";
import type { RiskDecision } from "@/lib/types";

const LIMIT_LABELS: Record<string, string> = {
  max_position_pct: "Max position",
  max_portfolio_exposure_pct: "Max exposure",
  max_leverage: "Max leverage",
  max_daily_loss_pct: "Daily loss budget",
  max_drawdown_pct: "Max drawdown",
  max_volatility: "Max volatility",
  max_order_value: "Max order value",
  gross_breach_multiple: "Gross-breach multiple",
  reject_score: "Reject at score",
  reduce_score: "Reduce at score",
  max_adverse_probability: "Max adverse probability (ML)",
};

function DecisionDetail({ decision }: { decision: RiskDecision }) {
  return (
    <tr className="border-b border-rule/60 bg-sunken/50">
      <td colSpan={7} className="px-3 py-3">
        <p className="mb-2 text-[11px] uppercase tracking-wider text-muted">
          Check breakdown — what was measured against what is allowed
        </p>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-[12px]">
            <thead>
              <tr className="text-[10px] uppercase tracking-wider text-muted">
                <th className="px-2 py-1 text-left">Check</th>
                <th className="px-2 py-1 text-left">Result</th>
                <th className="px-2 py-1 text-right">Observed</th>
                <th className="px-2 py-1 text-right">Limit</th>
                <th className="px-2 py-1 text-right">Utilisation</th>
                <th className="px-2 py-1 text-right">Score</th>
              </tr>
            </thead>
            <tbody>
              {decision.checks.map((c) => (
                <tr key={c.name} className="border-t border-rule/40">
                  <td className="px-2 py-1 font-mono text-ink-2">{c.name}</td>
                  <td className="px-2 py-1">
                    <span className={c.passed ? "text-good" : "text-critical"}>
                      {c.passed ? "✓ pass" : "✕ fail"}
                    </span>
                  </td>
                  <td className="tabular px-2 py-1 text-right">
                    {c.observed ? num(c.observed).toFixed(4) : "—"}
                  </td>
                  <td className="tabular px-2 py-1 text-right">
                    {c.limit ? num(c.limit).toFixed(4) : "—"}
                  </td>
                  <td className="tabular px-2 py-1 text-right">
                    {c.utilisation ? `${num(c.utilisation).toFixed(2)}x` : "—"}
                  </td>
                  <td className="tabular px-2 py-1 text-right font-medium">
                    {num(c.score).toFixed(0)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {decision.reasons.length > 0 && (
          <ul className="mt-2 space-y-1">
            {decision.reasons.map((r) => (
              <li key={r} className="text-[12px] text-critical">— {r}</li>
            ))}
          </ul>
        )}
      </td>
    </tr>
  );
}

export default function RiskPage() {
  const [filter, setFilter] = useState<string | undefined>(undefined);
  const [open, setOpen] = useState<string | null>(null);

  const summary = useApi(() => api.riskSummary());
  const decisions = useApi(() => api.riskDecisions(60, filter), [filter]);

  if (summary.error) return <ErrorState message={summary.error} />;
  if (!summary.data) return <Loading label="Loading risk data" />;
  const s = summary.data;

  const total = Object.values(s.decision_counts).reduce((a, b) => a + b, 0);

  return (
    <>
      <PageHeader
        title="Risk"
        description="Every proposed trade is scored and either approved, resized or refused. Refusals are stored with the numbers behind them."
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile label="Decisions" value={String(total)} hint="all time" />
        <StatTile label="Approval rate" value={pct(s.approval_rate, 1)} />
        <StatTile
          label="Rejected"
          value={String(s.decision_counts.REJECT ?? 0)}
          tone="critical"
        />
        <StatTile
          label="Reduced"
          value={String(s.decision_counts.REDUCE ?? 0)}
          hint="sized down to fit a limit"
        />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card title="Current posture">
          <RiskMeter score={num(s.current_score)} />
        </Card>
        <Card title="Verdict mix">
          <VerdictBars counts={s.decision_counts} />
        </Card>
        <Card title="What refuses trades" subtitle="Failed checks, most frequent first">
          <RejectionReasons reasons={s.rejection_reasons} />
        </Card>
      </div>

      <Card
        className="mt-4"
        title="Configured limits"
        subtitle="One validated object drives the live engine, the backtester and this view"
      >
        <div className="grid gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
          {Object.entries(s.limits).map(([k, v]) => (
            <div key={k} className="flex justify-between border-b border-rule/60 py-1.5 text-[13px]">
              <span className="text-muted">{LIMIT_LABELS[k] ?? k}</span>
              <span className="tabular font-medium text-ink">
                {k.endsWith("_pct") ? pct(v, 1) : k === "max_order_value" ? money(v, 0) : num(v).toFixed(2)}
              </span>
            </div>
          ))}
        </div>
      </Card>

      <Card
        className="mt-4"
        title="Decision log"
        subtitle="Click a row to see the check-by-check breakdown"
        action={
          <div className="flex gap-1">
            {[undefined, "APPROVE", "REDUCE", "REJECT"].map((f) => (
              <button
                key={f ?? "all"}
                onClick={() => setFilter(f)}
                className={`rounded border px-2 py-1 text-[11px] ${
                  filter === f
                    ? "border-accent bg-accent-soft text-accent"
                    : "border-rule text-ink-2 hover:bg-sunken"
                }`}
              >
                {f ?? "All"}
              </button>
            ))}
          </div>
        }
      >
        {decisions.error ? (
          <ErrorState message={decisions.error} />
        ) : decisions.data ? (
          <Table
            head={["Time", "Symbol", "Strategy", "Verdict", "Score", "Requested → Approved", "Reasons"]}
            empty={!decisions.data.length}
          >
            {decisions.data.map((d) => (
              <>
                <tr
                  key={d.id}
                  onClick={() => setOpen(open === d.id ? null : d.id)}
                  className="cursor-pointer border-b border-rule/60 hover:bg-sunken/60"
                >
                  <Cell mono>{time(d.created_at)}</Cell>
                  <Cell mono>{d.symbol ?? "—"}</Cell>
                  <Cell>{d.strategy ?? "—"}</Cell>
                  <Cell><VerdictBadge action={d.action} /></Cell>
                  <Cell mono align="right">{num(d.score).toFixed(0)}</Cell>
                  <Cell mono align="right">
                    {num(d.requested_quantity).toFixed(4)} → {num(d.approved_quantity).toFixed(4)}
                  </Cell>
                  <Cell className="max-w-[22rem] truncate text-[12px] text-ink-2">
                    {d.reasons.length ? d.reasons.join(" · ") : "—"}
                  </Cell>
                </tr>
                {open === d.id && <DecisionDetail key={`${d.id}-detail`} decision={d} />}
              </>
            ))}
          </Table>
        ) : (
          <Loading />
        )}
      </Card>
    </>
  );
}

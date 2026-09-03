"use client";

/**
 * Charts.
 *
 * Rules applied throughout:
 *  - one y-axis, never two;
 *  - a single series carries no legend (the card title names it), two or more
 *    always do;
 *  - series colours come from the fixed categorical slots and are assigned by
 *    entity, never by rank, so filtering never repaints the survivors;
 *  - status colours (good/warning/critical) are reserved for verdicts and are
 *    never used as a series identity;
 *  - grid and axes are recessive; every chart has a hover layer.
 */

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { compactMoney, money, num, pct, shortTime } from "@/lib/format";

const GRID = "var(--grid)";
const AXIS = "var(--axis)";
const MUTED = "var(--muted)";

const axisProps = {
  stroke: AXIS,
  tick: { fill: MUTED, fontSize: 11 },
  tickLine: false,
  axisLine: { stroke: AXIS },
};

function TooltipBox({
  label,
  rows,
}: {
  label?: string;
  rows: { name: string; value: string; color?: string }[];
}) {
  return (
    <div className="rounded border border-rule bg-surface px-2.5 py-2 shadow-lg">
      {label && <p className="mb-1 text-[11px] text-muted">{label}</p>}
      {rows.map((r) => (
        <div key={r.name} className="flex items-center gap-2 text-[12px]">
          {r.color && (
            <span
              className="inline-block h-2 w-2 rounded-sm"
              style={{ background: r.color }}
              aria-hidden="true"
            />
          )}
          <span className="text-muted">{r.name}</span>
          <span className="tabular ml-auto font-medium text-ink">{r.value}</span>
        </div>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------- equity */

export function EquityCurve({
  data,
  height = 260,
  baseline,
}: {
  data: { timestamp: string; equity: string }[];
  height?: number;
  baseline?: number;
}) {
  const points = data.map((d) => ({
    t: shortTime(d.timestamp),
    iso: d.timestamp,
    equity: num(d.equity),
  }));

  if (points.length < 2) {
    return (
      <div className="flex h-[260px] items-center justify-center text-[13px] text-muted">
        Not enough history to plot an equity curve yet.
      </div>
    );
  }

  const values = points.map((p) => p.equity);
  const lo = Math.min(...values, baseline ?? Infinity);
  const hi = Math.max(...values, baseline ?? -Infinity);
  const pad = (hi - lo) * 0.12 || hi * 0.01;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={points} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
        <defs>
          <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--series-1)" stopOpacity={0.22} />
            <stop offset="100%" stopColor="var(--series-1)" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="t" {...axisProps} minTickGap={48} />
        <YAxis
          {...axisProps}
          width={62}
          domain={[lo - pad, hi + pad]}
          tickFormatter={(v: number) => compactMoney(v)}
        />
        {baseline !== undefined && (
          // The opening balance: the line that separates making money from losing it.
          <ReferenceLine
            y={baseline}
            stroke={AXIS}
            strokeDasharray="3 3"
            label={{
              value: "start",
              position: "insideTopLeft",
              fill: MUTED,
              fontSize: 10,
            }}
          />
        )}
        <Tooltip
          cursor={{ stroke: AXIS, strokeWidth: 1 }}
          content={({ active, payload }) =>
            active && payload?.length ? (
              <TooltipBox
                label={shortTime(payload[0].payload.iso)}
                rows={[
                  {
                    name: "Equity",
                    value: money(payload[0].value as number),
                    color: "var(--series-1)",
                  },
                ]}
              />
            ) : null
          }
        />
        <Area
          type="monotone"
          dataKey="equity"
          stroke="var(--series-1)"
          strokeWidth={2}
          fill="url(#equityFill)"
          dot={false}
          activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)" }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

/* ------------------------------------------------------------ price line */

export function PriceChart({
  bars,
  height = 300,
}: {
  bars: { close_time: string; close: string; high: string; low: string }[];
  height?: number;
}) {
  const points = bars.map((b) => ({
    t: shortTime(b.close_time),
    iso: b.close_time,
    close: num(b.close),
  }));

  if (points.length < 2) {
    return (
      <div className="flex h-[300px] items-center justify-center text-[13px] text-muted">
        No price history stored for this symbol.
      </div>
    );
  }

  const values = points.map((p) => p.close);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const pad = (hi - lo) * 0.08 || hi * 0.01;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={points} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="t" {...axisProps} minTickGap={56} />
        <YAxis
          {...axisProps}
          width={68}
          domain={[lo - pad, hi + pad]}
          tickFormatter={(v: number) => compactMoney(v)}
        />
        <Tooltip
          cursor={{ stroke: AXIS, strokeWidth: 1 }}
          content={({ active, payload }) =>
            active && payload?.length ? (
              <TooltipBox
                label={shortTime(payload[0].payload.iso)}
                rows={[
                  {
                    name: "Close",
                    value: money(payload[0].value as number),
                    color: "var(--series-1)",
                  },
                ]}
              />
            ) : null
          }
        />
        <Line
          type="monotone"
          dataKey="close"
          stroke="var(--series-1)"
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)" }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

/* ------------------------------------------------- strategy attribution */

const SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"];

/** Colour follows the entity, not its position, so sorting cannot repaint it. */
export function seriesColor(name: string, order: string[]): string {
  const index = order.indexOf(name);
  return SERIES[(index < 0 ? 0 : index) % SERIES.length];
}

export function StrategyPnl({
  data,
  order,
  height = 240,
}: {
  data: { name: string; realized_pnl: string }[];
  order: string[];
  height?: number;
}) {
  const points = data.map((d) => ({ name: d.name, pnl: num(d.realized_pnl) }));
  if (!points.length) {
    return <div className="py-10 text-center text-[13px] text-muted">No strategy activity yet.</div>;
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart
        data={points}
        layout="vertical"
        margin={{ top: 4, right: 56, bottom: 4, left: 8 }}
      >
        <CartesianGrid stroke={GRID} horizontal={false} />
        <XAxis type="number" {...axisProps} tickFormatter={(v: number) => compactMoney(v)} />
        <YAxis
          type="category"
          dataKey="name"
          {...axisProps}
          width={104}
          tick={{ fill: "var(--ink-2)", fontSize: 11 }}
        />
        <ReferenceLine x={0} stroke={AXIS} />
        <Tooltip
          cursor={{ fill: "var(--sunken)" }}
          content={({ active, payload }) =>
            active && payload?.length ? (
              <TooltipBox
                label={payload[0].payload.name}
                rows={[
                  {
                    name: "Realised P&L",
                    value: money(payload[0].value as number),
                    color: seriesColor(payload[0].payload.name, order),
                  },
                ]}
              />
            ) : null
          }
        />
        <Bar dataKey="pnl" radius={[0, 4, 4, 0]} barSize={18} isAnimationActive={false}>
          {points.map((p) => (
            <Cell key={p.name} fill={seriesColor(p.name, order)} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

/* ------------------------------------------------------- risk verdicts */

/**
 * Verdict mix. Uses the reserved status palette because these ARE statuses,
 * not series - and each bar is directly labelled so colour is never the only
 * carrier of meaning.
 */
export function VerdictBars({
  counts,
}: {
  counts: Record<string, number>;
}) {
  const order: { key: string; label: string; color: string }[] = [
    { key: "APPROVE", label: "Approved", color: "var(--good)" },
    { key: "REDUCE", label: "Reduced", color: "var(--warning)" },
    { key: "REJECT", label: "Rejected", color: "var(--critical)" },
  ];
  const total = order.reduce((sum, o) => sum + (counts[o.key] ?? 0), 0);

  if (!total) {
    return <div className="py-6 text-center text-[13px] text-muted">No decisions recorded yet.</div>;
  }

  return (
    <div className="space-y-3">
      {order.map((o) => {
        const value = counts[o.key] ?? 0;
        const share = value / total;
        return (
          <div key={o.key}>
            <div className="mb-1 flex items-baseline justify-between text-[12px]">
              <span className="text-ink-2">{o.label}</span>
              <span className="tabular text-muted">
                <span className="font-medium text-ink">{value}</span> · {pct(share, 1)}
              </span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-sunken">
              <div
                className="h-full rounded-full"
                style={{ width: `${share * 100}%`, background: o.color }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** Which checks refuse trades most often - a magnitude comparison, one hue. */
export function RejectionReasons({ reasons }: { reasons: Record<string, number> }) {
  const entries = Object.entries(reasons);
  if (!entries.length) {
    return (
      <div className="py-6 text-center text-[13px] text-muted">
        No checks have refused a trade.
      </div>
    );
  }
  const max = Math.max(...entries.map(([, v]) => v));

  return (
    <div className="space-y-2.5">
      {entries.map(([name, count]) => (
        <div key={name} className="grid grid-cols-[9.5rem_1fr_2.5rem] items-center gap-3">
          <span className="truncate font-mono text-[11px] text-ink-2">{name}</span>
          <div className="h-2 w-full overflow-hidden rounded-full bg-sunken">
            <div
              className="h-full rounded-full"
              style={{ width: `${(count / max) * 100}%`, background: "var(--series-1)" }}
            />
          </div>
          <span className="tabular text-right text-[12px] font-medium text-ink">{count}</span>
        </div>
      ))}
    </div>
  );
}

/** Share of gross exposure by symbol. Bars, not a pie: lengths compare, angles don't. */
export function AllocationBars({
  allocation,
  order,
}: {
  allocation: Record<string, string>;
  order: string[];
}) {
  const entries = Object.entries(allocation);
  if (!entries.length) {
    return <div className="py-6 text-center text-[13px] text-muted">No open exposure.</div>;
  }

  return (
    <div className="space-y-3">
      {entries.map(([symbol, share]) => (
        <div key={symbol}>
          <div className="mb-1 flex items-baseline justify-between text-[12px]">
            <span className="font-mono text-ink-2">{symbol}</span>
            <span className="tabular font-medium text-ink">{pct(share, 1)}</span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-sunken">
            <div
              className="h-full rounded-full"
              style={{
                width: `${num(share) * 100}%`,
                background: seriesColor(symbol, order),
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

/* --------------------------------------------------- backtest comparison */

export function BacktestCurve({
  data,
  baseline,
  height = 280,
}: {
  data: { timestamp: string; equity: string }[];
  baseline: number;
  height?: number;
}) {
  return <EquityCurve data={data} baseline={baseline} height={height} />;
}

export { Legend };

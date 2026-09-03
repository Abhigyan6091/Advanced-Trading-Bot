"use client";

import type { ReactNode } from "react";
import { isUp, num } from "@/lib/format";

/* --------------------------------------------------------------------------
   Primitives.

   Border, fill and shadow are spent by role rather than stamped on every
   block: a Card is a surface, a StatTile is a surface with a figure, and a
   Badge is the only thing that carries status colour.
   -------------------------------------------------------------------------- */

export function Card({
  title,
  subtitle,
  action,
  children,
  className = "",
}: {
  title?: string;
  subtitle?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-md border border-rule bg-surface ${className}`}
    >
      {(title || action) && (
        <header className="flex items-start justify-between gap-4 border-b border-rule px-4 py-3">
          <div>
            {title && (
              <h2 className="text-[13px] font-semibold tracking-tight text-ink">
                {title}
              </h2>
            )}
            {subtitle && (
              <p className="mt-0.5 text-[11px] text-muted">{subtitle}</p>
            )}
          </div>
          {action}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function StatTile({
  label,
  value,
  delta,
  deltaLabel,
  hint,
  tone = "neutral",
}: {
  label: string;
  value: string;
  delta?: string | number | null;
  deltaLabel?: string;
  hint?: string;
  tone?: "neutral" | "good" | "critical";
}) {
  const toneClass =
    tone === "good" ? "text-good" : tone === "critical" ? "text-critical" : "text-ink";

  return (
    <div className="rounded-md border border-rule bg-surface px-4 py-3">
      <p className="text-[11px] uppercase tracking-wider text-muted">{label}</p>
      <p className={`mt-1.5 text-2xl font-semibold tabular tracking-tight ${toneClass}`}>
        {value}
      </p>
      <div className="mt-1 flex items-baseline gap-2">
        {delta !== undefined && delta !== null && (
          <span
            className={`text-[12px] font-medium tabular ${
              isUp(delta) ? "text-good" : "text-critical"
            }`}
          >
            {isUp(delta) ? "▲" : "▼"} {deltaLabel ?? String(delta)}
          </span>
        )}
        {hint && <span className="text-[11px] text-muted">{hint}</span>}
      </div>
    </div>
  );
}

/**
 * Status badge.
 *
 * Status colour never travels alone: the label is always present, so the
 * meaning survives colourblindness, greyscale printing and forced-colors mode.
 */
export function Badge({
  children,
  tone = "neutral",
  icon,
}: {
  children: ReactNode;
  tone?: "neutral" | "good" | "warning" | "critical" | "accent";
  icon?: string;
}) {
  const tones: Record<string, string> = {
    neutral: "bg-sunken text-ink-2 border-rule",
    good: "bg-[var(--good-bg)] text-good border-[var(--good)]/30",
    warning: "bg-[var(--warning-bg)] text-[#8a6100] dark:text-warning border-[var(--warning)]/30",
    critical: "bg-[var(--critical-bg)] text-critical border-[var(--critical)]/30",
    accent: "bg-accent-soft text-accent border-accent/30",
  };
  return (
    <span
      className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${tones[tone]}`}
    >
      {icon && <span aria-hidden="true">{icon}</span>}
      {children}
    </span>
  );
}

/** Maps a risk verdict onto its reserved status colour and icon. */
export function VerdictBadge({ action }: { action: string }) {
  if (action === "APPROVE") return <Badge tone="good" icon="✓">Approve</Badge>;
  if (action === "REDUCE") return <Badge tone="warning" icon="◐">Reduce</Badge>;
  if (action === "REJECT") return <Badge tone="critical" icon="✕">Reject</Badge>;
  return <Badge>{action}</Badge>;
}

export function SideBadge({ side }: { side: string }) {
  return (
    <span
      className={`font-mono text-[11px] font-semibold ${
        side === "BUY" ? "text-good" : "text-critical"
      }`}
    >
      {side}
    </span>
  );
}

/** A 0-100 risk score with a proportional meter. Higher is riskier. */
export function RiskMeter({ score, label }: { score: number; label?: string }) {
  const tone = score >= 75 ? "critical" : score >= 45 ? "warning" : "good";
  const color =
    tone === "critical"
      ? "var(--critical)"
      : tone === "warning"
        ? "var(--warning)"
        : "var(--good)";

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-[11px] uppercase tracking-wider text-muted">
          {label ?? "Risk score"}
        </span>
        <span className="tabular text-sm font-semibold text-ink">
          {score.toFixed(0)}
          <span className="text-muted"> / 100</span>
        </span>
      </div>
      <div
        className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-sunken"
        role="meter"
        aria-valuenow={Math.round(score)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Risk score, higher is riskier"
      >
        <div
          className="h-full rounded-full"
          style={{ width: `${Math.min(100, Math.max(0, score))}%`, background: color }}
        />
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-muted">
        <span>Approve</span>
        <span>Reduce 45</span>
        <span>Reject 75</span>
      </div>
    </div>
  );
}

export function Table({
  head,
  children,
  empty,
}: {
  head: string[];
  children: ReactNode;
  empty?: boolean;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-left text-[13px]">
        <thead>
          <tr className="border-b border-rule">
            {head.map((h) => (
              <th
                key={h}
                className="whitespace-nowrap px-3 py-2 text-[10px] font-medium uppercase tracking-wider text-muted"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
      {empty && <EmptyState>Nothing recorded yet.</EmptyState>}
    </div>
  );
}

export function Row({ children }: { children: ReactNode }) {
  return <tr className="border-b border-rule/60 last:border-0">{children}</tr>;
}

export function Cell({
  children,
  mono = false,
  align = "left",
  className = "",
}: {
  children: ReactNode;
  mono?: boolean;
  align?: "left" | "right";
  className?: string;
}) {
  return (
    <td
      className={`px-3 py-2 ${align === "right" ? "text-right" : ""} ${
        mono ? "font-mono tabular text-[12px]" : ""
      } ${className}`}
    >
      {children}
    </td>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="px-3 py-10 text-center text-[13px] text-muted">{children}</div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="rounded-md border border-[var(--critical)]/30 bg-[var(--critical-bg)] px-4 py-3">
      <p className="text-[13px] font-medium text-critical">Could not load this data</p>
      <p className="mt-1 text-[12px] text-ink-2">{message}</p>
    </div>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="px-3 py-10 text-center text-[13px] text-muted" role="status">
      {label}…
    </div>
  );
}

export function PnL({ value, dp = 2 }: { value: string | number; dp?: number }) {
  const n = num(value);
  return (
    <span className={`tabular font-medium ${n >= 0 ? "text-good" : "text-critical"}`}>
      {n >= 0 ? "+" : "−"}
      {Math.abs(n).toLocaleString("en-US", {
        minimumFractionDigits: dp,
        maximumFractionDigits: dp,
      })}
    </span>
  );
}

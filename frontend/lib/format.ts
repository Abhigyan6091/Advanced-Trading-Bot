/**
 * Formatting helpers.
 *
 * The API sends every decimal as a string so no precision is lost in transit.
 * These helpers are the only place those strings become numbers, and that
 * happens for display only -- never for arithmetic that feeds back to the API.
 */

export const num = (value: string | number | null | undefined): number =>
  value === null || value === undefined ? 0 : Number(value);

export function money(value: string | number | null | undefined, dp = 2): string {
  return num(value).toLocaleString("en-US", {
    minimumFractionDigits: dp,
    maximumFractionDigits: dp,
  });
}

export function compactMoney(value: string | number | null | undefined): string {
  const n = num(value);
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return n.toFixed(2);
}

export function pct(value: string | number | null | undefined, dp = 2): string {
  return `${(num(value) * 100).toFixed(dp)}%`;
}

export function signed(value: string | number | null | undefined, dp = 2): string {
  const n = num(value);
  return `${n >= 0 ? "+" : "-"}${Math.abs(n).toLocaleString("en-US", {
    minimumFractionDigits: dp,
    maximumFractionDigits: dp,
  })}`;
}

export function signedPct(value: string | number | null | undefined, dp = 2): string {
  const n = num(value) * 100;
  return `${n >= 0 ? "+" : ""}${n.toFixed(dp)}%`;
}

/** Trims a Decimal string to a sensible number of places without rounding up. */
export function qty(value: string | number | null | undefined, dp = 4): string {
  const n = num(value);
  return n.toFixed(dp).replace(/\.?0+$/, "") || "0";
}

export function time(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function shortTime(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
  });
}

export const isUp = (value: string | number | null | undefined): boolean => num(value) >= 0;

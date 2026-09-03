/**
 * API client.
 *
 * Every call goes through `request`, so a failure is surfaced with the server's
 * own message rather than an opaque "fetch failed". The dashboard renders that
 * message; it never silently shows an empty panel that looks like "no data"
 * when the real answer is "the API is down".
 */

import type {
  Bar,
  BacktestResult,
  EquityPoint,
  Fill,
  Market,
  Order,
  Overview,
  Performance,
  Portfolio,
  RiskDecision,
  RiskSummary,
  Signal,
  Strategy,
} from "./types";

const BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    throw new ApiError(
      `Cannot reach the API at ${BASE}. Is the backend running?`,
      0,
    );
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      /* the body was not JSON; the status text stands */
    }
    throw new ApiError(detail, response.status);
  }

  return response.json() as Promise<T>;
}

export const api = {
  overview: () => request<Overview>("/api/overview"),
  portfolio: () => request<Portfolio>("/api/portfolio"),
  equityCurve: () => request<EquityPoint[]>("/api/portfolio/equity-curve"),
  allocation: () => request<Record<string, string>>("/api/portfolio/allocation"),
  fills: (limit = 50) => request<Fill[]>(`/api/portfolio/fills?limit=${limit}`),

  riskSummary: () => request<RiskSummary>("/api/risk/summary"),
  riskDecisions: (limit = 50, action?: string) =>
    request<RiskDecision[]>(
      `/api/risk/decisions?limit=${limit}${action ? `&action=${action}` : ""}`,
    ),
  rejections: (limit = 50) =>
    request<RiskDecision[]>(`/api/risk/rejections?limit=${limit}`),

  orders: (limit = 50, symbol?: string) =>
    request<Order[]>(`/api/orders?limit=${limit}${symbol ? `&symbol=${symbol}` : ""}`),
  orderStats: () => request<Record<string, number>>("/api/orders/stats"),
  signals: (limit = 50, strategy?: string) =>
    request<Signal[]>(
      `/api/signals?limit=${limit}${strategy ? `&strategy=${strategy}` : ""}`,
    ),

  markets: () => request<Market[]>("/api/markets"),
  bars: (symbol: string, interval = "1h", limit = 200) =>
    request<Bar[]>(`/api/markets/${symbol}/bars?interval=${interval}&limit=${limit}`),

  strategies: () => request<Strategy[]>("/api/strategies"),
  catalogue: () =>
    request<Record<string, { parameters: Record<string, unknown>; min_bars: number }>>(
      "/api/strategies/catalogue",
    ),

  performance: () => request<Performance>("/api/performance"),

  backtest: (body: {
    strategy: string;
    symbol: string;
    interval: string;
    bars: number;
    parameters?: Record<string, unknown>;
  }) =>
    request<BacktestResult>("/api/backtest", {
      method: "POST",
      body: JSON.stringify({ starting_balance: "100000", ...body }),
    }),
};

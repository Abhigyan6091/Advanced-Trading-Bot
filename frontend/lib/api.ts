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

const TOKEN_KEY = "sta-token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private mode: the session simply does not persist across reloads */
  }
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Thrown on 401 so callers can distinguish "not logged in" from other failures. */
export class UnauthorizedError extends ApiError {
  constructor(message: string) {
    super(message, 401);
    this.name = "UnauthorizedError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      cache: "no-store",
      ...init,
      headers: { ...headers, ...(init?.headers as Record<string, string> | undefined) },
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
    if (response.status === 401) {
      setToken(null);
      throw new UnauthorizedError(detail);
    }
    throw new ApiError(detail, response.status);
  }

  return response.json() as Promise<T>;
}

export const api = {
  login: (username: string, password: string) =>
    request<{ access_token: string; token_type: string; role: string }>(
      "/api/auth/login",
      { method: "POST", body: JSON.stringify({ username, password }) },
    ),
  me: () => request<{ username: string; role: string }>("/api/auth/me"),

  aiAnalystAvailability: () =>
    request<{ available: boolean; model: string | null }>("/api/ai-analyst/availability"),
  aiAnalystAsk: (question: string) =>
    request<{ answer: string; tools_used: string[] }>("/api/ai-analyst/ask", {
      method: "POST",
      body: JSON.stringify({ question }),
    }),

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

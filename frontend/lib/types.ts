/** Response shapes, mirroring app/api/schemas.py. Decimals arrive as strings. */

export interface Position {
  symbol: string;
  side: string;
  quantity: string;
  signed_quantity: string;
  average_entry_price: string;
  mark_price: string | null;
  notional: string | null;
  unrealized_pnl: string | null;
  realized_pnl: string;
}

export interface Portfolio {
  equity: string;
  cash: string;
  position_value: string;
  starting_balance: string;
  realized_pnl: string;
  unrealized_pnl: string;
  total_pnl: string;
  total_return: string;
  total_commission: string;
  gross_exposure: string;
  leverage: string;
  drawdown: string;
  peak_equity: string;
  daily_pnl: string;
  open_position_count: number;
  positions: Position[];
  as_of: string;
}

export interface Overview {
  portfolio: Portfolio;
  risk_score: string;
  open_orders: number;
  signals_today: number;
  rejected_today: number;
  strategies: number;
  broker: string;
  live_trading: boolean;
}

export interface EquityPoint {
  timestamp: string;
  equity: string;
}

export interface RiskCheck {
  name: string;
  passed: boolean;
  score: string;
  weight: string;
  observed: string | null;
  limit: string | null;
  utilisation: string | null;
  reason: string;
}

export interface RiskDecision {
  id: string;
  signal_id: string | null;
  symbol: string | null;
  strategy: string | null;
  action: "APPROVE" | "REDUCE" | "REJECT";
  score: string;
  requested_quantity: string;
  approved_quantity: string;
  reasons: string[];
  checks: RiskCheck[];
  created_at: string;
}

export interface RiskSummary {
  limits: Record<string, string>;
  decision_counts: Record<string, number>;
  rejection_reasons: Record<string, number>;
  current_score: string;
  approval_rate: string;
  recent: RiskDecision[];
}

export interface Order {
  id: string;
  client_order_id: string;
  exchange_order_id: string | null;
  symbol: string;
  side: string;
  order_type: string;
  status: string;
  quantity: string;
  filled_quantity: string;
  price: string | null;
  average_fill_price: string | null;
  risk_decision_id: string | null;
  signal_id: string | null;
  created_at: string;
}

export interface Fill {
  id: string;
  order_id: string;
  symbol: string;
  side: string;
  quantity: string;
  price: string;
  commission: string;
  executed_at: string;
}

export interface Signal {
  id: string;
  strategy: string;
  symbol: string;
  action: string;
  strength: string;
  reference_price: string;
  bar_close_time: string;
  created_at: string;
  features: Record<string, unknown>;
}

export interface Market {
  symbol: string;
  base_asset: string;
  quote_asset: string;
  tick_size: string;
  step_size: string;
  min_quantity: string;
  min_notional: string;
  max_leverage: number;
  last_price: string | null;
  change_24h: string | null;
}

export interface Bar {
  open_time: string;
  close_time: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
}

export interface Strategy {
  name: string;
  parameters: Record<string, unknown>;
  signals: number;
  actionable: number;
  approved: number;
  reduced: number;
  rejected: number;
  realized_pnl: string;
}

export interface Performance {
  starting_equity: string;
  ending_equity: string;
  total_return: string;
  sharpe_ratio: string;
  sortino_ratio: string;
  max_drawdown: string;
  calmar_ratio: string | null;
  win_rate: string;
  profit_factor: string | null;
  expectancy: string;
  average_win: string;
  average_loss: string;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
}

export interface BacktestResult {
  strategy: string;
  symbol: string;
  interval: string;
  bars_processed: number;
  signals: number;
  executed: number;
  rejected: number;
  performance: Performance;
  equity_curve: EquityPoint[];
  rejection_reasons: Record<string, number>;
  open_position_pnl: string;
}

/**
 * ACIE Frontend Types
 *
 * IMPORTANT — PERCENT UNIT CONTRACT:
 * All *_pct fields from the backend API are FRACTIONS (0–1), NOT percentages.
 * Examples: 0.034 = 3.4%, 0.10 = 10%, 0.02 = 2%
 * Frontend components MUST multiply by 100 before displaying as "%".
 * Comparison thresholds must use fraction values (e.g. > 0.06, not > 6).
 *
 * Exceptions (already in % or score form):
 *   - win_rate:        0–100 (percent, no multiply needed)
 *   - discipline_score: 0–100 (score, no multiply needed)
 */

export type RiskMode = 'NORMAL' | 'CAUTION' | 'DEFENSE' | 'LOCKED';
export type TradeDirection = 'LONG' | 'SHORT';
export type PositionStatus = 'OPEN' | 'CLOSED';

export interface Trader {
  id: number;
  name: string;
  account_id: string;
  starting_equity: number;
  // Policy A fields
  realised_equity: number;
  peak_realised_equity: number;
  unrealised_pnl: number;
  total_equity: number;
  risk_mode: RiskMode;
  is_locked: boolean;
  cooldown_until: string | null;
  consecutive_losses: number;
  daily_loss_today: number;
  recovery_streak: number;
  discipline_score: number;
  active: boolean;
  created_at: string;
}

export interface TraderSummary {
  id: number;
  name: string;
  account_id: string;
  total_equity: number;
  realised_equity: number;
  risk_mode: RiskMode;
  is_locked: boolean;
  discipline_score: number;
}

export interface Trade {
  id: number;
  trader_id: number;
  position_id: number | null;
  symbol: string;
  direction: TradeDirection;
  quantity: number;
  entry_price: number;
  exit_price: number | null;
  realised_pnl: number | null;
  commission: number;
  is_closed: boolean;
  risk_mode_at_entry: RiskMode;
  opened_at: string;
  closed_at: string | null;
  notes: string | null;
}

export interface Position {
  id: number;
  trader_id: number;
  symbol: string;
  direction: TradeDirection;
  net_quantity: number;
  average_entry_price: number;
  mark_price: number | null;
  unrealised_pnl: number;
  exposure_value: number;
  status: PositionStatus;
  opened_at: string;
  closed_at: string | null;
}

export interface RiskLimits {
  /** fraction 0–1 — multiply by 100 for display */
  base_risk_pct: number;
  /** fraction 0–1 — multiply by 100 for display */
  exposure_cap_pct: number;
  /** fraction 0–1 — multiply by 100 for display */
  daily_loss_cap_pct: number;
  risk_mode: RiskMode;
}

export interface DashboardMetrics {
  trader_id: number;
  account_id: string;
  name: string;
  // Equity breakdown (currency values)
  total_equity: number;
  realised_equity: number;
  unrealised_pnl: number;
  starting_equity: number;
  peak_realised_equity: number;
  // Drawdown — Policy A — ALL FRACTIONS (0–1), multiply by 100 for display
  /** fraction 0–1 — PRIMARY governance/lock trigger (realised-only, Policy A) */
  realised_drawdown_pct: number;
  /** fraction 0–1 — WARNING ONLY, never triggers lock */
  unrealised_drawdown_pct: number;
  /** fraction 0–1 — current exposure / total equity */
  exposure_pct: number;
  // Win rate is already in percent (0–100), no multiply needed
  win_rate: number;
  // Discipline score is 0–100, no multiply needed
  discipline_score: number;
  // Risk state
  risk_mode: RiskMode;
  is_locked: boolean;
  cooldown_active: boolean;
  cooldown_until: string | null;
  /** fraction 0–1 — daily loss / starting equity */
  daily_loss_pct: number;
  /** fraction 0–1 — current mode daily loss cap */
  daily_loss_cap_pct: number;
  consecutive_losses: number;
  recovery_streak: number;
  unrealised_warning: boolean;
  // Counts
  open_positions_count: number;
  total_trades: number;
  // Limits — all fractions 0–1 inside RiskLimits
  risk_limits: RiskLimits;
}

export interface EquitySnapshot {
  id: number;
  total_equity: number;
  equity: number;                      // alias for total_equity
  realised_equity: number;
  peak_realised_equity: number;
  unrealised_pnl: number;
  /** fraction 0–1 */
  realised_drawdown_pct: number;
  /** fraction 0–1 */
  unrealised_drawdown_pct: number;
  /** fraction 0–1 — alias for realised_drawdown_pct */
  drawdown_pct: number;
  risk_mode: RiskMode;
  snapshot_at: string;
}

export interface GovernanceNote {
  id: number;
  trader_id: number;
  author: string;
  note_type: string;
  content: string;
  risk_mode_at_note: RiskMode | null;
  created_at: string;
}

export interface RiskStatus {
  trader_id: number;
  risk_mode: RiskMode;
  is_locked: boolean;
  /** fraction 0–1 */
  realised_drawdown_pct: number;
  /** fraction 0–1 */
  unrealised_drawdown_pct: number;
  /** fraction 0–1 */
  exposure_pct: number;
  /** fraction 0–1 */
  daily_loss_pct: number;
  /** fraction 0–1 */
  daily_loss_cap_pct: number;
  /** fraction 0–1 */
  exposure_cap_pct: number;
  /** fraction 0–1 */
  base_risk_pct: number;
  consecutive_losses: number;
  cooldown_until: string | null;
  cooldown_active: boolean;
  discipline_score: number;
  recovery_streak: number;
  unrealised_warning: boolean;
}

// Form payloads
export interface TradeCreatePayload {
  symbol: string;
  direction: TradeDirection;
  quantity: number;
  entry_price: number;
  commission?: number;
  notes?: string;
}

export interface TradeClosePayload {
  exit_price: number;
  commission?: number;
}

export interface MarkToMarketPayload {
  mark_price: number;
}

export interface GovernanceNotePayload {
  author: string;
  note_type: string;
  content: string;
}

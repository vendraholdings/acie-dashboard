import React from 'react';
import type { DashboardMetrics } from '../../types';
import { KpiCard } from '../ui/KpiCard';
import { RiskBadge } from '../ui/RiskBadge';
import { formatCurrency, RISK_MODE_COLOR, pnlColor } from '../../utils/format';

/**
 * KpiRow — top-level metric strip.
 *
 * All *_pct values from DashboardMetrics are FRACTIONS (0–1).
 * Multiply by 100 before display. Use fraction thresholds for comparisons.
 */

interface KpiRowProps {
  metrics: DashboardMetrics;
}

export const KpiRow: React.FC<KpiRowProps> = ({ metrics }) => {
  // Fractions for comparison — NOT multiplied
  const realisedDd = metrics.realised_drawdown_pct;  // fraction 0–1
  const unrealisedDd = metrics.unrealised_drawdown_pct;  // fraction 0–1
  const dailyLoss = metrics.daily_loss_pct;  // fraction 0–1
  const dailyCap = metrics.daily_loss_cap_pct;  // fraction 0–1

  const realisedDdColor =
    realisedDd > 0.06
      ? '#ff2a4a'
      : realisedDd > 0.03
      ? '#ffd700'
      : '#00ff9d';

  const dailyLossColor =
    dailyCap > 0 && dailyLoss / dailyCap >= 0.9
      ? '#ff2a4a'
      : dailyCap > 0 && dailyLoss / dailyCap >= 0.6
      ? '#ffd700'
      : '#00ff9d';

  return (
    <div className="kpi-row">
      <KpiCard
        label="Total Equity"
        value={formatCurrency(metrics.total_equity)}
        sub={`Start: ${formatCurrency(metrics.starting_equity)}`}
        accent="#e2e8f0"
      />
      <KpiCard
        label="Realised Equity"
        value={formatCurrency(metrics.realised_equity)}
        sub={`Peak: ${formatCurrency(metrics.peak_realised_equity)}`}
        accent="#60a5fa"
      />
      <KpiCard
        label="Unrealised PnL"
        value={formatCurrency(metrics.unrealised_pnl)}
        sub="Display only"
        accent={pnlColor(metrics.unrealised_pnl)}
      />
      {/* PRIMARY drawdown KPI — governance/lock source (realised-only, Policy A) */}
      <KpiCard
        label="Drawdown % (Realised)"
        value={`${(realisedDd * 100).toFixed(2)}%`}
        sub="Governance trigger"
        accent={realisedDdColor}
        alert={realisedDd > 0.06}
      />
      {/* SECONDARY drawdown KPI — warning only, never triggers lock */}
      <KpiCard
        label="Unrealised DD (Warn)"
        value={`${(unrealisedDd * 100).toFixed(2)}%`}
        sub="Warning only"
        accent={metrics.unrealised_warning ? '#ff8c00' : '#4a5568'}
        alert={false}
      />
      {/* Daily loss vs cap */}
      <KpiCard
        label="Daily Loss"
        value={`${(dailyLoss * 100).toFixed(2)}%`}
        sub={`Cap: ${(dailyCap * 100).toFixed(2)}%`}
        accent={dailyLossColor}
        alert={dailyCap > 0 && dailyLoss >= dailyCap}
      />
      <KpiCard
        label="Exposure"
        value={`${(metrics.exposure_pct * 100).toFixed(2)}%`}
        sub={`Cap: ${(metrics.risk_limits.exposure_cap_pct * 100).toFixed(0)}%`}
        accent="#60a5fa"
      />
      <KpiCard
        label="Win Rate"
        value={`${metrics.win_rate.toFixed(1)}%`}
        accent={metrics.win_rate > 50 ? '#00ff9d' : '#ff8c00'}
      />
      <KpiCard
        label="Discipline"
        value={`${metrics.discipline_score.toFixed(0)}/100`}
        accent={
          metrics.discipline_score > 70
            ? '#00ff9d'
            : metrics.discipline_score > 40
            ? '#ffd700'
            : '#ff2a4a'
        }
      />
      <div className="kpi-card kpi-card--mode">
        <span className="kpi-label">Risk Mode</span>
        <RiskBadge mode={metrics.risk_mode} large />
      </div>
    </div>
  );
};

import React from 'react';
import type { DashboardMetrics } from '../../types';
import { RiskBadge } from '../ui/RiskBadge';
import { ProgressBar } from '../ui/ProgressBar';
import { Panel } from '../ui/Panel';
import { formatCurrency, formatDate, RISK_MODE_COLOR } from '../../utils/format';

/**
 * AcieStatusPanel — governance status display.
 *
 * All *_pct values from DashboardMetrics are FRACTIONS (0–1).
 * This component multiplies by 100 for all display text.
 * ProgressBar receives values in the same unit as its `max` prop.
 * We pass values × 100 and max × 100 so both are in percent (0–100).
 */

interface AcieStatusPanelProps {
  metrics: DashboardMetrics;
  onUnlock?: () => void;
}

export const AcieStatusPanel: React.FC<AcieStatusPanelProps> = ({ metrics, onUnlock }) => {
  const modeColor = RISK_MODE_COLOR[metrics.risk_mode];

  // Convert fractions to percent for display
  const realisedDdPct = metrics.realised_drawdown_pct * 100;
  const unrealisedDdPct = metrics.unrealised_drawdown_pct * 100;
  const dailyLossPct = metrics.daily_loss_pct * 100;
  const dailyCapPct = metrics.daily_loss_cap_pct * 100;
  const exposurePct = metrics.exposure_pct * 100;
  const exposureCapPct = metrics.risk_limits.exposure_cap_pct * 100;

  return (
    <Panel title="ACIE STATUS">
      <div className="status-panel">

        {/* Policy badge */}
        <div className="policy-badge">
          <span className="policy-badge__icon">⚖</span>
          <span className="policy-badge__text">LOCK based on REALISED equity (Policy A)</span>
        </div>

        <div className="status-panel__mode">
          <RiskBadge mode={metrics.risk_mode} large />

          {metrics.is_locked && (
            <div className="status-panel__lock">
              <span className="lock-icon">⛔</span>
              <span>ACCOUNT LOCKED</span>
              {onUnlock && (
                <button className="btn btn--ghost btn--sm" onClick={onUnlock}>
                  Unlock
                </button>
              )}
            </div>
          )}

          {metrics.cooldown_active && (
            <div className="status-panel__cooldown">
              <span>🕐 COOLDOWN ACTIVE</span>
              {metrics.cooldown_until && (
                <span className="cooldown-until">Until {formatDate(metrics.cooldown_until)}</span>
              )}
            </div>
          )}

          {/* Unrealised warning callout — shown when not locked */}
          {metrics.unrealised_warning && !metrics.is_locked && (
            <div className="status-panel__unreal-warn">
              <span className="unreal-warn__icon">⚠</span>
              <div className="unreal-warn__body">
                <span className="unreal-warn__title">Unrealised drawdown elevated</span>
                <span className="unreal-warn__detail">
                  {unrealisedDdPct.toFixed(2)}% vs realised {realisedDdPct.toFixed(2)}%
                </span>
                <span className="unreal-warn__policy">
                  Unrealised drawdown only — does not affect lock per Policy A
                </span>
              </div>
            </div>
          )}

          {/* Daily loss cap warning — shown when approaching cap */}
          {!metrics.is_locked && dailyCapPct > 0 && dailyLossPct / dailyCapPct >= 0.75 && (
            <div className="status-panel__unreal-warn" style={{ borderColor: '#f59e0b' }}>
              <span className="unreal-warn__icon">💸</span>
              <div className="unreal-warn__body">
                <span className="unreal-warn__title">Daily loss cap approaching</span>
                <span className="unreal-warn__detail">
                  {dailyLossPct.toFixed(2)}% used of {dailyCapPct.toFixed(2)}% cap
                </span>
                <span className="unreal-warn__policy">
                  Breach will LOCK trading for the day (server-enforced)
                </span>
              </div>
            </div>
          )}
        </div>

        <div className="status-grid">
          <div className="status-item">
            <span className="status-item__label">Peak Realised</span>
            <span className="status-item__value">{formatCurrency(metrics.peak_realised_equity)}</span>
          </div>
          <div className="status-item">
            <span className="status-item__label">Loss Streak</span>
            <span className="status-item__value" style={{ color: metrics.consecutive_losses >= 2 ? '#ff2a4a' : '#e2e8f0' }}>
              {metrics.consecutive_losses}×
            </span>
          </div>
          <div className="status-item">
            <span className="status-item__label">Recovery</span>
            <span className="status-item__value" style={{ color: metrics.recovery_streak > 0 ? '#00ff9d' : '#4a5568' }}>
              {metrics.recovery_streak}/3
            </span>
          </div>
          <div className="status-item">
            <span className="status-item__label">Open Pos.</span>
            <span className="status-item__value">{metrics.open_positions_count}</span>
          </div>
        </div>

        <div className="status-gauges">
          {/* Drawdown: value 0–100 (pct), max 10 (%) */}
          <ProgressBar
            label="Realised Drawdown (governance)"
            value={realisedDdPct}
            max={10}
            color={modeColor}
          />
          <ProgressBar
            label="Unrealised Drawdown (warning)"
            value={unrealisedDdPct}
            max={10}
            color={metrics.unrealised_warning ? '#ff8c00' : '#4a5568'}
          />
          {/* Exposure: value 0–100 (pct), max = cap in pct */}
          <ProgressBar
            label="Exposure"
            value={exposurePct}
            max={exposureCapPct > 0 ? exposureCapPct : 30}
            color="#60a5fa"
          />
          {/* Daily loss: value 0–100 (pct), max = cap in pct */}
          <ProgressBar
            label="Daily Loss"
            value={dailyLossPct}
            max={dailyCapPct > 0 ? dailyCapPct : 2}
            color="#f59e0b"
          />
          {/* Discipline: already 0–100 score */}
          <ProgressBar
            label="Discipline Score"
            value={metrics.discipline_score}
            max={100}
            color="#a78bfa"
          />
        </div>
      </div>
    </Panel>
  );
};

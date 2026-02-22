from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timezone, timedelta
from typing import List
from fastapi import HTTPException

from app.models.models import Trader, Trade, Position, EquitySnapshot, GovernanceNote, RiskMode, PositionStatus
from app.schemas.schemas import TraderCreate, TraderUpdate, DashboardMetrics, RiskLimits
from app.risk_engine import evaluate_state, get_risk_params, is_cooldown_active


def create_trader(db: Session, payload: TraderCreate) -> Trader:
    if db.query(Trader).filter(Trader.account_id == payload.account_id).first():
        raise HTTPException(status_code=400, detail="Account ID already exists")

    trader = Trader(
        name=payload.name,
        account_id=payload.account_id,
        starting_equity=payload.starting_equity,
        realised_equity=payload.starting_equity,
        peak_realised_equity=payload.starting_equity,
        unrealised_pnl=0.0,
        total_equity=payload.starting_equity,
    )
    db.add(trader)
    db.commit()
    db.refresh(trader)
    return trader


def get_trader(db: Session, trader_id: int) -> Trader:
    trader = db.query(Trader).filter(Trader.id == trader_id).first()
    if not trader:
        raise HTTPException(status_code=404, detail="Trader not found")
    return trader


def get_trader_by_account(db: Session, account_id: str) -> Trader:
    trader = db.query(Trader).filter(Trader.account_id == account_id).first()
    if not trader:
        raise HTTPException(status_code=404, detail="Trader not found")
    return trader


def list_traders(db: Session, active_only: bool = True) -> List[Trader]:
    query = db.query(Trader)
    if active_only:
        query = query.filter(Trader.active == True)
    return query.order_by(Trader.created_at.desc()).all()


def update_trader(db: Session, trader_id: int, payload: TraderUpdate) -> Trader:
    trader = get_trader(db, trader_id)
    if payload.name is not None:
        trader.name = payload.name
    if payload.active is not None:
        trader.active = payload.active
    db.commit()
    db.refresh(trader)
    return trader


def unlock_trader(db: Session, trader_id: int) -> Trader:
    """Governance unlock — only operation that can de-escalate from LOCKED."""
    trader = get_trader(db, trader_id)
    prev_mode = trader.risk_mode

    trader.is_locked = False
    trader.risk_mode = RiskMode.NORMAL
    trader.consecutive_losses = 0
    trader.cooldown_until = None
    trader.recovery_streak = 0
    # Also reset daily loss so re-lock doesn't immediately re-trigger
    trader.daily_loss_today = 0.0

    note = GovernanceNote(
        trader_id=trader.id,
        author="SYSTEM",
        note_type="OVERRIDE",
        content=(
            f"Manual governance unlock applied. Previous mode: {prev_mode}. "
            f"Account restored to NORMAL. Realised drawdown at time of unlock: "
            f"{_realised_drawdown_pct(trader) * 100:.2f}%. "
            f"Daily loss reset to zero."
        ),
        risk_mode_at_note=RiskMode.NORMAL,
    )
    db.add(note)
    db.commit()
    db.refresh(trader)
    return trader


def reset_daily_loss(db: Session, trader_id: int) -> Trader:
    trader = get_trader(db, trader_id)
    trader.daily_loss_today = 0.0
    trader.daily_reset_date = datetime.now(timezone.utc)
    db.commit()
    db.refresh(trader)
    return trader


def _realised_drawdown_pct(trader: Trader) -> float:
    if trader.peak_realised_equity <= 0:
        return 0.0
    return max(0.0, (trader.peak_realised_equity - trader.realised_equity) / trader.peak_realised_equity)


def sync_trader_equity(db: Session, trader: Trader) -> Trader:
    """
    Recompute display equity from realised + open positions.
    Run risk evaluation (Policy A) and persist state changes.
    Auto-generates governance notes on mode change, lock trigger, or unrealised warning.
    """
    open_positions = (
        db.query(Position)
        .filter(Position.trader_id == trader.id, Position.status == PositionStatus.OPEN)
        .all()
    )
    unrealised_pnl = sum(p.unrealised_pnl for p in open_positions)
    open_notional = sum(p.exposure_value for p in open_positions)

    # Update display fields
    trader.unrealised_pnl = unrealised_pnl
    trader.total_equity = trader.realised_equity + unrealised_pnl

    # Update peak (realised only — Policy A)
    if trader.realised_equity > trader.peak_realised_equity:
        trader.peak_realised_equity = trader.realised_equity

    prev_mode = trader.risk_mode

    eval_result = evaluate_state(
        trader=trader,
        open_notional=open_notional,
        daily_realised_pnl=trader.daily_loss_today,
        now_ts=datetime.now(timezone.utc),
    )

    trader.risk_mode = eval_result.risk_mode
    trader.is_locked = eval_result.is_locked
    trader.recovery_streak = eval_result.new_recovery_streak
    trader.discipline_score = eval_result.discipline_score

    db.flush()

    # ── Auto-generate governance notes ────────────────────────────────────────
    # All pct values from engine are fractions (0–1); multiply by 100 for display in notes.
    realised_dd = eval_result.realised_drawdown_pct * 100
    unrealised_dd = eval_result.unrealised_drawdown_pct * 100
    daily_loss_pct_display = eval_result.daily_loss_pct * 100

    if eval_result.lock_triggered:
        if eval_result.daily_loss_lock:
            # Lock caused by daily loss cap breach
            params_at_lock = eval_result.params
            # The cap that was breached is from the mode before LOCKED was forced;
            # retrieve it from the pre-lock mode params via the engine's check logic.
            # For note clarity, recompute cap from prev_mode.
            from app.risk_engine.engine import RISK_PARAMS as _RP
            pre_lock_mode = prev_mode if prev_mode != RiskMode.LOCKED else RiskMode.DEFENSE
            cap_pct_display = _RP[pre_lock_mode]["daily_loss_cap"] * 100
            note = GovernanceNote(
                trader_id=trader.id,
                author="RISK ENGINE",
                note_type="LOCK",
                content=(
                    f"ACCOUNT LOCKED due to DAILY LOSS CAP breach. "
                    f"Daily loss: {daily_loss_pct_display:.2f}% of starting equity "
                    f"(cap: {cap_pct_display:.2f}% for {pre_lock_mode} mode). "
                    f"Realised drawdown at lock: {realised_dd:.2f}%. "
                    f"Lock is enforced server-side. Manual governance unlock required. "
                    f"Daily loss is realised-only — consistent with Policy A."
                ),
                risk_mode_at_note=RiskMode.LOCKED,
            )
        else:
            # Lock caused by realised drawdown
            note = GovernanceNote(
                trader_id=trader.id,
                author="RISK ENGINE",
                note_type="LOCK",
                content=(
                    f"ACCOUNT LOCKED. Realised drawdown reached {realised_dd:.2f}% "
                    f"(threshold: 10.00%). All new trade creation is blocked. "
                    f"Manual governance unlock required. "
                    f"Unrealised drawdown at lock: {unrealised_dd:.2f}% "
                    f"(display only — does not affect lock per Policy A)."
                ),
                risk_mode_at_note=RiskMode.LOCKED,
            )
        db.add(note)

    elif eval_result.mode_changed:
        note = GovernanceNote(
            trader_id=trader.id,
            author="RISK ENGINE",
            note_type="MODE_CHANGE",
            content=(
                f"Risk mode changed: {prev_mode} → {eval_result.risk_mode}. "
                f"Realised drawdown: {realised_dd:.2f}% "
                f"(NORMAL<3%, CAUTION≥3%, DEFENSE≥6%, LOCKED≥10%). "
                f"Unrealised drawdown: {unrealised_dd:.2f}% "
                f"(warning only — does not affect mode per Policy A). "
                f"Exposure cap now {eval_result.params['exposure_cap'] * 100:.0f}%, "
                f"daily loss cap {eval_result.params['daily_loss_cap'] * 100:.2f}%."
            ),
            risk_mode_at_note=eval_result.risk_mode,
        )
        db.add(note)

    if eval_result.unrealised_warning and not eval_result.lock_triggered:
        note = GovernanceNote(
            trader_id=trader.id,
            author="RISK ENGINE",
            note_type="WARNING",
            content=(
                f"Unrealised drawdown warning: {unrealised_dd:.2f}% "
                f"is materially worse than realised drawdown {realised_dd:.2f}%. "
                f"Unrealised drawdown only — does not affect lock per Policy A. "
                f"Monitor open positions."
            ),
            risk_mode_at_note=eval_result.risk_mode,
        )
        db.add(note)

    # ── Equity snapshot ────────────────────────────────────────────────────────
    snapshot = EquitySnapshot(
        trader_id=trader.id,
        total_equity=trader.total_equity,
        equity=trader.total_equity,
        realised_equity=trader.realised_equity,
        peak_realised_equity=trader.peak_realised_equity,
        unrealised_pnl=unrealised_pnl,
        realised_drawdown_pct=eval_result.realised_drawdown_pct,    # stored as fraction
        unrealised_drawdown_pct=eval_result.unrealised_drawdown_pct,  # stored as fraction
        drawdown_pct=eval_result.realised_drawdown_pct,              # alias, fraction
        risk_mode=trader.risk_mode,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(trader)
    return trader


def get_dashboard_metrics(db: Session, trader_id: int) -> DashboardMetrics:
    trader = get_trader(db, trader_id)

    open_positions = (
        db.query(Position)
        .filter(Position.trader_id == trader_id, Position.status == PositionStatus.OPEN)
        .all()
    )
    unrealised_pnl = sum(p.unrealised_pnl for p in open_positions)
    open_notional = sum(p.exposure_value for p in open_positions)

    total_trades = db.query(func.count(Trade.id)).filter(Trade.trader_id == trader_id).scalar() or 0
    winning_trades = (
        db.query(func.count(Trade.id))
        .filter(Trade.trader_id == trader_id, Trade.is_closed == True, Trade.realised_pnl > 0)
        .scalar()
        or 0
    )
    closed_trades = (
        db.query(func.count(Trade.id))
        .filter(Trade.trader_id == trader_id, Trade.is_closed == True)
        .scalar()
        or 0
    )
    win_rate = (winning_trades / closed_trades * 100) if closed_trades > 0 else 0.0

    eval_result = evaluate_state(
        trader=trader,
        open_notional=open_notional,
        daily_realised_pnl=trader.daily_loss_today,
        now_ts=datetime.now(timezone.utc),
    )
    params = get_risk_params(trader.risk_mode)

    # NOTE: All *_pct values returned here are fractions (0–1).
    # Frontend multiplies by 100 for display.
    return DashboardMetrics(
        trader_id=trader.id,
        account_id=trader.account_id,
        name=trader.name,
        total_equity=trader.realised_equity + unrealised_pnl,
        realised_equity=trader.realised_equity,
        unrealised_pnl=unrealised_pnl,
        starting_equity=trader.starting_equity,
        peak_realised_equity=trader.peak_realised_equity,
        realised_drawdown_pct=round(eval_result.realised_drawdown_pct, 6),   # fraction 0–1
        unrealised_drawdown_pct=round(eval_result.unrealised_drawdown_pct, 6),  # fraction 0–1
        exposure_pct=round(eval_result.exposure_pct, 6),                      # fraction 0–1
        win_rate=round(win_rate, 2),                                           # already %
        discipline_score=trader.discipline_score,                              # 0–100 score
        risk_mode=trader.risk_mode,
        is_locked=trader.is_locked,
        cooldown_active=is_cooldown_active(trader.cooldown_until),
        cooldown_until=trader.cooldown_until,
        daily_loss_pct=round(eval_result.daily_loss_pct, 6),                  # fraction 0–1
        daily_loss_cap_pct=params["daily_loss_cap"],                           # fraction 0–1
        consecutive_losses=trader.consecutive_losses,
        recovery_streak=trader.recovery_streak,
        unrealised_warning=eval_result.unrealised_warning,
        open_positions_count=len(open_positions),
        total_trades=total_trades,
        risk_limits=RiskLimits(
            base_risk_pct=params["base_risk"],                  # fraction 0–1
            exposure_cap_pct=params["exposure_cap"],            # fraction 0–1
            daily_loss_cap_pct=params["daily_loss_cap"],        # fraction 0–1
            risk_mode=trader.risk_mode,
        ),
    )

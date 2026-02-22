from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta
from typing import List
from fastapi import HTTPException

from app.models.models import Trade, Trader, Position, GovernanceNote, TradeDirection, PositionStatus, RiskMode
from app.schemas.schemas import TradeCreate, TradeClose
from app.risk_engine import (
    evaluate_state, get_risk_params,
    check_exposure_breach,
    is_cooldown_active,
    CONSECUTIVE_LOSS_COOLDOWN,
    COOLDOWN_HOURS,
    RISK_PARAMS,
)
from app.services import position_service
from app.services import trader_service


def _assert_can_trade(trader: Trader) -> None:
    """
    Service-layer enforcement of all trade-blocking conditions:
    1. Account locked (drawdown or daily loss cap breach)
    2. Cooldown active (loss streak)
    3. Daily loss cap already breached for today

    All checks use fractions (0–1) consistent with engine contract.
    """
    if trader.is_locked or trader.risk_mode == RiskMode.LOCKED:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "ACCOUNT_LOCKED",
                "message": "Trader account is LOCKED. No trades permitted. Manual governance unlock required.",
                "risk_mode": trader.risk_mode,
            },
        )

    if is_cooldown_active(trader.cooldown_until):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "COOLDOWN_ACTIVE",
                "message": f"Trader is in cooldown until {trader.cooldown_until.isoformat()}.",
                "cooldown_until": trader.cooldown_until.isoformat(),
            },
        )

    # Daily loss cap hard check (pre-trade, before lock propagates via sync)
    if trader.starting_equity > 0:
        daily_loss_pct = trader.daily_loss_today / trader.starting_equity  # fraction
        mode_params = RISK_PARAMS.get(trader.risk_mode, RISK_PARAMS[RiskMode.NORMAL])
        cap = mode_params["daily_loss_cap"]  # fraction
        if cap > 0 and daily_loss_pct >= cap:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "DAILY_LOSS_BREACH",
                    "message": "Daily loss cap breached. Trading locked for the day.",
                    "daily_loss_pct": f"{daily_loss_pct * 100:.2f}%",
                    "cap_pct": f"{cap * 100:.2f}%",
                    "risk_mode": trader.risk_mode,
                },
            )


def log_trade(db: Session, trader_id: int, payload: TradeCreate) -> Trade:
    trader = trader_service.get_trader(db, trader_id)
    _assert_can_trade(trader)

    open_positions = (
        db.query(Position)
        .filter(Position.trader_id == trader_id, Position.status == PositionStatus.OPEN)
        .all()
    )
    open_notional = sum(p.exposure_value for p in open_positions)
    new_trade_notional = payload.quantity * payload.entry_price
    total_equity = trader.realised_equity + trader.unrealised_pnl

    eval_result = evaluate_state(
        trader=trader,
        open_notional=open_notional,
        daily_realised_pnl=trader.daily_loss_today,
        now_ts=datetime.now(timezone.utc),
    )
    params = eval_result.params

    if check_exposure_breach(open_notional, new_trade_notional, total_equity, params):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "EXPOSURE_BREACH",
                "message": (
                    f"Trade rejected: adding ${new_trade_notional:,.0f} notional would breach "
                    f"the {params['exposure_cap'] * 100:.0f}% exposure cap "
                    f"for mode {eval_result.risk_mode}."
                ),
            },
        )

    position = position_service.get_or_create_position(
        db, trader_id, payload.symbol, payload.direction
    )

    trade = Trade(
        trader_id=trader_id,
        position_id=position.id,
        symbol=payload.symbol,
        direction=payload.direction,
        quantity=payload.quantity,
        entry_price=payload.entry_price,
        commission=payload.commission,
        risk_mode_at_entry=eval_result.risk_mode,
        notes=payload.notes,
    )
    db.add(trade)
    position_service.net_into_position(db, position, payload.quantity, payload.entry_price)
    db.commit()
    db.refresh(trade)

    trader_service.sync_trader_equity(db, trader)
    return trade


def close_trade(db: Session, trader_id: int, trade_id: int, payload: TradeClose) -> Trade:
    trade = db.query(Trade).filter(Trade.id == trade_id, Trade.trader_id == trader_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    if trade.is_closed:
        raise HTTPException(status_code=400, detail="Trade already closed")

    trader = trader_service.get_trader(db, trader_id)

    if trade.direction == TradeDirection.LONG:
        raw_pnl = (payload.exit_price - trade.entry_price) * trade.quantity
    else:
        raw_pnl = (trade.entry_price - payload.exit_price) * trade.quantity

    realised_pnl = raw_pnl - payload.commission - trade.commission

    trade.exit_price = payload.exit_price
    trade.realised_pnl = realised_pnl
    trade.is_closed = True
    trade.closed_at = datetime.now(timezone.utc)
    trade.commission = trade.commission + payload.commission

    # Update realised equity (Policy A source of truth)
    trader.realised_equity += realised_pnl

    # Update daily realised loss tracking (realised-only)
    if realised_pnl < 0:
        trader.daily_loss_today += abs(realised_pnl)

    # Loss streak tracking and cooldown
    now_ts = datetime.now(timezone.utc)
    if realised_pnl < 0:
        trader.consecutive_losses += 1
        if trader.consecutive_losses >= CONSECUTIVE_LOSS_COOLDOWN:
            trader.cooldown_until = now_ts + timedelta(hours=COOLDOWN_HOURS)
            note = GovernanceNote(
                trader_id=trader.id,
                author="RISK ENGINE",
                note_type="COOLDOWN",
                content=(
                    f"Cooldown triggered after {trader.consecutive_losses} consecutive losses. "
                    f"New trades blocked until {trader.cooldown_until.isoformat()}. "
                    f"Realised equity: ${trader.realised_equity:,.2f}."
                ),
                risk_mode_at_note=trader.risk_mode,
            )
            db.add(note)
    else:
        trader.consecutive_losses = 0

    # Reduce position
    if trade.position_id:
        position_service.reduce_position_on_close(db, trade.position_id, trade.quantity)

    db.commit()
    db.refresh(trade)

    # sync_trader_equity will also check daily loss cap and lock if breached
    trader_service.sync_trader_equity(db, trader)
    return trade


def list_trades(db: Session, trader_id: int, limit: int = 100) -> List[Trade]:
    trader_service.get_trader(db, trader_id)
    return (
        db.query(Trade)
        .filter(Trade.trader_id == trader_id)
        .order_by(Trade.opened_at.desc())
        .limit(limit)
        .all()
    )


def get_trade(db: Session, trader_id: int, trade_id: int) -> Trade:
    trade = db.query(Trade).filter(Trade.id == trade_id, Trade.trader_id == trader_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    return trade

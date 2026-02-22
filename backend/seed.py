"""
Seed script – Policy A demo data.

Three traders:
  ACC-001 (NORMAL)  — healthy, low drawdown, daily loss well below cap
  ACC-002 (CAUTION) — realised drawdown ~3.8%, daily loss below cap, unrealised warning
  ACC-003 (LOCKED)  — locked via DAILY LOSS CAP breach (DEFENSE mode cap = 0.75%)
                       demonstrating the new hard-stop enforcement path

Run: python seed.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app.database import SessionLocal, engine, Base
from app.models.models import (
    Trader, Trade, Position, EquitySnapshot, GovernanceNote,
    RiskMode, TradeDirection, PositionStatus,
)
from datetime import datetime, timezone, timedelta
import random

Base.metadata.create_all(bind=engine)
random.seed(42)


def _dd(peak: float, current: float) -> float:
    return max(0.0, (peak - current) / peak) if peak > 0 else 0.0


def seed():
    db = SessionLocal()
    try:
        for model in [GovernanceNote, EquitySnapshot, Trade, Position, Trader]:
            db.query(model).delete()
        db.commit()

        # ── ACC-001: NORMAL, healthy ──────────────────────────────────────────
        # Realised drawdown ~1.2% (well below 3% CAUTION threshold)
        # Daily loss today = $0 (no losses today)
        t1_start = 100_000.0
        t1_realised = 101_800.0   # +1.8% realised gain
        t1_peak_r = 102_400.0     # previous high → realised DD = (102400-101800)/102400 ≈ 0.59%
        t1_unrealised = 1_300.0   # open position gain (display only)

        t1 = Trader(
            name="Marcus Vega",
            account_id="ACC-001",
            starting_equity=t1_start,
            realised_equity=t1_realised,
            peak_realised_equity=t1_peak_r,
            unrealised_pnl=t1_unrealised,
            total_equity=t1_realised + t1_unrealised,
            risk_mode=RiskMode.NORMAL,
            is_locked=False,
            consecutive_losses=0,
            daily_loss_today=0.0,       # 0% daily loss — well under 2% NORMAL cap
            recovery_streak=0,
            discipline_score=91.5,
            active=True,
        )

        # ── ACC-002: CAUTION — realised drawdown ~3.8%, daily loss below cap ──
        # Realised drawdown 3.8% → CAUTION. Daily loss $350/$50k = 0.70% < 1.25% cap.
        t2_start = 50_000.0
        t2_peak_r = 51_000.0
        t2_realised = 49_062.0    # realised DD = (51000-49062)/51000 ≈ 3.8%
        t2_unrealised = -1_200.0  # open loss (display/warning only — not governance)

        t2 = Trader(
            name="Elena Zhao",
            account_id="ACC-002",
            starting_equity=t2_start,
            realised_equity=t2_realised,
            peak_realised_equity=t2_peak_r,
            unrealised_pnl=t2_unrealised,
            total_equity=t2_realised + t2_unrealised,
            risk_mode=RiskMode.CAUTION,
            is_locked=False,
            consecutive_losses=1,
            daily_loss_today=350.0,     # 0.70% of starting — below 1.25% CAUTION cap
            recovery_streak=0,
            discipline_score=72.0,
            active=True,
        )

        # ── ACC-003: LOCKED via daily loss cap breach ─────────────────────────
        # Mode was DEFENSE (realised DD ~7.4%). DEFENSE daily loss cap = 0.75%.
        # daily_loss_today = $1,600 / $200,000 starting = 0.80% >= 0.75% cap → LOCKED.
        # This demonstrates the new hard-stop daily loss enforcement path.
        t3_start = 200_000.0
        t3_peak_r = 202_000.0
        t3_realised = 187_052.0   # realised DD = (202000-187052)/202000 ≈ 7.4% → DEFENSE
        t3_unrealised = -3_000.0  # open loss (display only)
        # Daily loss: $1,600 / $200,000 = 0.80% >= 0.75% DEFENSE cap → LOCK triggered
        t3_daily_loss = 1_600.0

        t3 = Trader(
            name="James Okafor",
            account_id="ACC-003",
            starting_equity=t3_start,
            realised_equity=t3_realised,
            peak_realised_equity=t3_peak_r,
            unrealised_pnl=t3_unrealised,
            total_equity=t3_realised + t3_unrealised,
            risk_mode=RiskMode.LOCKED,
            is_locked=True,
            consecutive_losses=2,
            daily_loss_today=t3_daily_loss,  # 0.80% — breaches 0.75% DEFENSE cap
            recovery_streak=0,
            discipline_score=28.0,
            active=True,
        )

        db.add_all([t1, t2, t3])
        db.flush()

        # ── Closed trades for Marcus (ACC-001) ────────────────────────────────
        base_time = datetime.now(timezone.utc) - timedelta(days=30)
        symbols = ["AAPL", "NVDA", "TSLA", "SPY", "QQQ", "META"]
        pnl_series = [420, -180, 650, 310, -90, 780, -250, 540, 220, 890, -320, 410]

        for i, pnl in enumerate(pnl_series):
            sym = symbols[i % len(symbols)]
            qty = round(random.uniform(10, 50), 2)
            entry = round(random.uniform(150, 400), 2)
            direction = TradeDirection.LONG if pnl > 0 else TradeDirection.SHORT
            exit_p = round(entry + (pnl / qty if qty else 0), 2)
            db.add(Trade(
                trader_id=t1.id,
                symbol=sym,
                direction=direction,
                quantity=qty,
                entry_price=entry,
                exit_price=exit_p,
                realised_pnl=float(pnl),
                commission=2.5,
                is_closed=True,
                risk_mode_at_entry=RiskMode.NORMAL,
                opened_at=base_time + timedelta(days=i * 2, hours=9),
                closed_at=base_time + timedelta(days=i * 2, hours=14),
            ))

        # ── Closed trades for ACC-003 (showing today's losing trades) ─────────
        # Two losing trades today totalling -$1,600 realised loss
        today = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
        db.add(Trade(
            trader_id=t3.id,
            symbol="TSLA",
            direction=TradeDirection.SHORT,
            quantity=10.0,
            entry_price=220.0,
            exit_price=280.0,
            realised_pnl=-600.0,
            commission=5.0,
            is_closed=True,
            risk_mode_at_entry=RiskMode.DEFENSE,
            opened_at=today,
            closed_at=today + timedelta(hours=1),
        ))
        db.add(Trade(
            trader_id=t3.id,
            symbol="NVDA",
            direction=TradeDirection.LONG,
            quantity=5.0,
            entry_price=850.0,
            exit_price=650.0,
            realised_pnl=-1_000.0,
            commission=5.0,
            is_closed=True,
            risk_mode_at_entry=RiskMode.DEFENSE,
            opened_at=today + timedelta(hours=2),
            closed_at=today + timedelta(hours=3),
        ))

        # ── Open positions ─────────────────────────────────────────────────────
        pos1 = Position(
            trader_id=t1.id,
            symbol="NVDA",
            direction=TradeDirection.LONG,
            net_quantity=25.0,
            average_entry_price=485.0,
            mark_price=537.20,
            unrealised_pnl=t1_unrealised,
            exposure_value=25.0 * 537.20,
            status=PositionStatus.OPEN,
        )
        db.add(pos1)

        pos2 = Position(
            trader_id=t2.id,
            symbol="SPY",
            direction=TradeDirection.SHORT,
            net_quantity=20.0,
            average_entry_price=448.0,
            mark_price=508.0,
            unrealised_pnl=t2_unrealised,
            exposure_value=20.0 * 508.0,
            status=PositionStatus.OPEN,
        )
        db.add(pos2)

        pos3 = Position(
            trader_id=t3.id,
            symbol="AAPL",
            direction=TradeDirection.LONG,
            net_quantity=20.0,
            average_entry_price=185.0,
            mark_price=170.0,
            unrealised_pnl=t3_unrealised,
            exposure_value=20.0 * 170.0,
            status=PositionStatus.OPEN,
        )
        db.add(pos3)

        # ── Equity snapshots for Marcus (30 days) ─────────────────────────────
        realised = t1_start
        peak_r = t1_start
        for i in range(31):
            delta = random.uniform(-800, 1200)
            realised = max(90_000, realised + delta)
            peak_r = max(peak_r, realised)
            unreal = random.uniform(-500, 1500)
            total = realised + unreal
            r_dd = _dd(peak_r, realised)
            u_dd = _dd(peak_r, total)
            db.add(EquitySnapshot(
                trader_id=t1.id,
                total_equity=round(total, 2),
                equity=round(total, 2),
                realised_equity=round(realised, 2),
                peak_realised_equity=round(peak_r, 2),
                unrealised_pnl=round(unreal, 2),
                realised_drawdown_pct=round(r_dd, 6),   # fraction
                unrealised_drawdown_pct=round(u_dd, 6), # fraction
                drawdown_pct=round(r_dd, 6),             # alias, fraction
                risk_mode=RiskMode.NORMAL,
                snapshot_at=base_time + timedelta(days=i),
            ))

        # ── Governance notes ───────────────────────────────────────────────────
        notes_data = [
            (t1.id, "Risk Manager", "REVIEW",
             "Q1 performance review: ACC-001 operating within all governance limits. "
             "Realised drawdown ~0.59% — well below CAUTION threshold. "
             "Daily loss: $0 (0.00% of starting equity). "
             "Policy: LOCK based on REALISED equity only (Policy A)."),
            (t2.id, "Risk Manager", "MODE_CHANGE",
             "ACC-002 entered CAUTION mode. Realised drawdown 3.80% (threshold: 3.00%). "
             "Unrealised drawdown ~6.18% — WARNING ONLY, does not affect lock per Policy A. "
             "Daily loss: $350 (0.70% of $50k starting) — below 1.25% CAUTION cap. "
             "Exposure cap reduced to 20%, daily loss cap 1.25%."),
            (t3.id, "Head of Risk", "LOCK",
             "ACCOUNT LOCKED due to DAILY LOSS CAP breach. "
             "Daily loss: $1,600 (0.80% of $200k starting equity). "
             "DEFENSE mode daily loss cap: 0.75%. "
             "Realised drawdown at lock: 7.40% (DEFENSE mode, not yet at 10% LOCKED threshold). "
             "Lock is enforced server-side. Manual governance unlock required. "
             "Daily loss is realised-only — consistent with Policy A."),
            (t3.id, "Head of Risk", "MODE_CHANGE",
             "Prior mode change: NORMAL → DEFENSE for ACC-003. "
             "Realised drawdown: 7.40% (DEFENSE threshold: ≥6.00%). "
             "Exposure cap: 10%, daily loss cap: 0.75%."),
            (t1.id, "Compliance", "AUDIT",
             "Monthly compliance audit passed for ACC-001. All trade logs reconciled. "
             "No governance breaches detected."),
        ]
        for trader_id, author, note_type, content in notes_data:
            mode = {t1.id: RiskMode.NORMAL, t2.id: RiskMode.CAUTION, t3.id: RiskMode.LOCKED}[trader_id]
            db.add(GovernanceNote(
                trader_id=trader_id,
                author=author,
                note_type=note_type,
                content=content,
                risk_mode_at_note=mode,
            ))

        db.commit()

        t3_daily_loss_pct = t3_daily_loss / t3_start * 100
        print("✓ Seed data loaded (Policy A + Daily Loss Cap patch)")
        print(f"  ACC-001 (NORMAL)  realised DD ~0.59%  daily loss $0 (0.00%)  unrealised PnL +${t1_unrealised:,.0f}")
        print(f"  ACC-002 (CAUTION) realised DD ~3.80%  daily loss $350 (0.70%)  unrealised PnL -${abs(t2_unrealised):,.0f}  [unrealised warning]")
        print(f"  ACC-003 (LOCKED)  realised DD ~7.40%  daily loss ${t3_daily_loss:,.0f} ({t3_daily_loss_pct:.2f}%) >= 0.75% DEFENSE cap  [DAILY LOSS LOCK]")

    except Exception as e:
        db.rollback()
        print(f"✗ Seed failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()

"""
ACIE Risk Engine – Policy A: Governance based on REALISED equity only.

Key invariants enforced here:
- drawdown_pct and mode escalation use peak_realised_equity vs realised_equity.
- unrealised_pnl is passed through for display and warning computation only.
- exposure_pct denominator is total_equity (realised + unrealised) per industry standard.
- daily_loss_pct denominator is starting_equity for a consistent fixed reference.
- Mode de-escalation uses recovery_streak on the Trader model (Option A).
- evaluate_state() has a deterministic signature; callers must supply open_notional
  and daily_realised_pnl explicitly — no ambiguous current_equity reads.
- Daily loss cap breach forces LOCKED immediately (hard stop). Because
  daily_loss_today is realised-only, this does NOT violate Policy A.

NEVER call evaluate_state() with trader.total_equity as a governance input.

ALL *_pct fields returned by this engine are fractions (0–1).
Callers and frontend must multiply by 100 for display.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.models.models import RiskMode, Trader


# ─── Escalation thresholds (realised drawdown, fractions 0–1) ────────────────
DRAWDOWN_CAUTION = 0.03   # ≥3%
DRAWDOWN_DEFENSE = 0.06   # ≥6%
DRAWDOWN_LOCKED  = 0.10   # ≥10%

# ─── De-escalation recovery buffers ──────────────────────────────────────────
RECOVERY_BUFFER_DEFENSE_TO_CAUTION = 0.05
RECOVERY_BUFFER_CAUTION_TO_NORMAL  = 0.02
RECOVERY_STREAK_REQUIRED = 3

# ─── Cooldown ─────────────────────────────────────────────────────────────────
CONSECUTIVE_LOSS_COOLDOWN = 3
COOLDOWN_HOURS = 4

# ─── Mode risk parameters (all fractions 0–1) ─────────────────────────────────
RISK_PARAMS: dict[RiskMode, dict] = {
    RiskMode.NORMAL:  {"base_risk": 0.005, "exposure_cap": 0.30, "daily_loss_cap": 0.020},
    RiskMode.CAUTION: {"base_risk": 0.005, "exposure_cap": 0.20, "daily_loss_cap": 0.0125},
    RiskMode.DEFENSE: {"base_risk": 0.005, "exposure_cap": 0.10, "daily_loss_cap": 0.0075},
    RiskMode.LOCKED:  {"base_risk": 0.000, "exposure_cap": 0.00, "daily_loss_cap": 0.000},
}


@dataclass
class RiskEvaluation:
    """Immutable result of evaluate_state(). All *_pct fields are fractions (0–1)."""
    # Governance metrics (realised-only) — fractions
    realised_drawdown_pct: float
    # Warning metric (unrealised included) — fraction, never triggers mode or lock
    unrealised_drawdown_pct: float
    # Mode outputs
    risk_mode: RiskMode
    is_locked: bool
    # Exposure and daily loss — fractions
    exposure_pct: float
    daily_loss_pct: float
    # Cooldown
    cooldown_active: bool
    # Recovery tracking
    new_recovery_streak: int
    # Discipline (0–100 score, not a fraction)
    discipline_score: float
    # Params for current mode
    params: dict
    # Auto-governance note triggers
    mode_changed: bool
    lock_triggered: bool
    cooldown_triggered: bool
    unrealised_warning: bool
    # True when lock was triggered specifically by daily loss cap (vs drawdown)
    daily_loss_lock: bool


def _compute_drawdown(peak: float, current: float) -> float:
    if peak <= 0:
        return 0.0
    return max(0.0, (peak - current) / peak)


def _determine_escalated_mode(realised_drawdown_pct: float) -> RiskMode:
    """Return the mode dictated by current realised drawdown (escalation only)."""
    if realised_drawdown_pct >= DRAWDOWN_LOCKED:
        return RiskMode.LOCKED
    if realised_drawdown_pct >= DRAWDOWN_DEFENSE:
        return RiskMode.DEFENSE
    if realised_drawdown_pct >= DRAWDOWN_CAUTION:
        return RiskMode.CAUTION
    return RiskMode.NORMAL


_MODE_RANK: dict[RiskMode, int] = {
    RiskMode.NORMAL: 0,
    RiskMode.CAUTION: 1,
    RiskMode.DEFENSE: 2,
    RiskMode.LOCKED: 3,
}


def _apply_de_escalation(
    current_mode: RiskMode,
    realised_drawdown_pct: float,
    current_recovery_streak: int,
) -> tuple[RiskMode, int]:
    """
    Option A de-escalation. LOCKED never auto-unlocks.
    Returns (effective_mode, new_recovery_streak).
    """
    if current_mode == RiskMode.LOCKED:
        return RiskMode.LOCKED, 0

    if current_mode == RiskMode.DEFENSE:
        if realised_drawdown_pct < RECOVERY_BUFFER_DEFENSE_TO_CAUTION:
            new_streak = current_recovery_streak + 1
            if new_streak >= RECOVERY_STREAK_REQUIRED:
                return RiskMode.CAUTION, 0
            return RiskMode.DEFENSE, new_streak
        return RiskMode.DEFENSE, 0

    if current_mode == RiskMode.CAUTION:
        if realised_drawdown_pct < RECOVERY_BUFFER_CAUTION_TO_NORMAL:
            new_streak = current_recovery_streak + 1
            if new_streak >= RECOVERY_STREAK_REQUIRED:
                return RiskMode.NORMAL, 0
            return RiskMode.CAUTION, new_streak
        return RiskMode.CAUTION, 0

    return RiskMode.NORMAL, 0


def evaluate_state(
    trader: Trader,
    open_notional: float,
    daily_realised_pnl: float,
    now_ts: datetime,
) -> RiskEvaluation:
    """
    Deterministic risk evaluation for a trader.

    Parameters
    ----------
    trader            : ORM Trader instance (read-only during this call)
    open_notional     : sum of position.exposure_value for all OPEN positions
    daily_realised_pnl: total realised losses today (positive number = loss)
    now_ts            : current UTC datetime for cooldown comparison

    Returns RiskEvaluation where ALL *_pct fields are fractions (0–1).

    Governance (Policy A)
    ---------------------
    Mode escalation uses realised equity vs peak_realised_equity.
    Unrealised PnL is display/warning only.

    Daily Loss Cap (hard stop, Policy A compliant)
    -----------------------------------------------
    daily_loss_today is realised-only. If daily_loss_pct >= mode cap,
    the account is LOCKED immediately (manual unlock required).
    """
    # ── Realised drawdown (governance) ────────────────────────────────────────
    realised_drawdown_pct = _compute_drawdown(
        trader.peak_realised_equity, trader.realised_equity
    )

    # ── Unrealised-inclusive drawdown (warning only) ──────────────────────────
    total_equity = trader.realised_equity + trader.unrealised_pnl
    unrealised_drawdown_pct = _compute_drawdown(
        trader.peak_realised_equity, total_equity
    )
    unrealised_warning = unrealised_drawdown_pct > realised_drawdown_pct + 0.01

    # ── Mode escalation by drawdown ───────────────────────────────────────────
    breach_mode = _determine_escalated_mode(realised_drawdown_pct)
    prev_rank = _MODE_RANK[trader.risk_mode]
    breach_rank = _MODE_RANK[breach_mode]

    if breach_rank > prev_rank:
        post_escalation_mode = breach_mode
        new_recovery_streak = 0
        mode_changed = True
    elif breach_rank == prev_rank:
        post_escalation_mode, new_recovery_streak = _apply_de_escalation(
            trader.risk_mode, realised_drawdown_pct, trader.recovery_streak
        )
        mode_changed = post_escalation_mode != trader.risk_mode
    else:
        post_escalation_mode, new_recovery_streak = _apply_de_escalation(
            trader.risk_mode, realised_drawdown_pct, trader.recovery_streak
        )
        mode_changed = post_escalation_mode != trader.risk_mode

    # ── Daily loss cap — hard stop ────────────────────────────────────────────
    # Determine the applicable cap from the pre-lock mode.
    # If drawdown already escalated to LOCKED, skip (already locking).
    daily_loss_pct = (
        daily_realised_pnl / trader.starting_equity
        if trader.starting_equity > 0
        else 0.0
    )

    daily_loss_lock = False
    if post_escalation_mode != RiskMode.LOCKED and not trader.is_locked:
        # Use the post-escalation (pre-daily-loss-check) mode's cap
        applicable_cap = RISK_PARAMS[post_escalation_mode]["daily_loss_cap"]
        if applicable_cap > 0 and daily_loss_pct >= applicable_cap:
            daily_loss_lock = True
            post_escalation_mode = RiskMode.LOCKED
            new_recovery_streak = 0
            mode_changed = True

    # ── Lock state ────────────────────────────────────────────────────────────
    lock_triggered = post_escalation_mode == RiskMode.LOCKED and not trader.is_locked
    is_locked = post_escalation_mode == RiskMode.LOCKED or trader.is_locked

    # ── Cooldown ───────────────────────────────────────────────────────────────
    cooldown_active = trader.cooldown_until is not None and now_ts < trader.cooldown_until
    cooldown_triggered = False

    params = RISK_PARAMS[post_escalation_mode]

    # ── Exposure % ────────────────────────────────────────────────────────────
    exposure_pct = (open_notional / total_equity) if total_equity > 0 else 0.0

    # ── Discipline score ───────────────────────────────────────────────────────
    discipline_score = _compute_discipline_score(
        realised_drawdown_pct=realised_drawdown_pct,
        daily_loss_pct=daily_loss_pct,
        consecutive_losses=trader.consecutive_losses,
        is_locked=is_locked,
        params=params,
    )

    return RiskEvaluation(
        realised_drawdown_pct=realised_drawdown_pct,
        unrealised_drawdown_pct=unrealised_drawdown_pct,
        risk_mode=post_escalation_mode,
        is_locked=is_locked,
        exposure_pct=exposure_pct,
        daily_loss_pct=daily_loss_pct,
        cooldown_active=cooldown_active,
        new_recovery_streak=new_recovery_streak,
        discipline_score=discipline_score,
        params=params,
        mode_changed=mode_changed,
        lock_triggered=lock_triggered,
        cooldown_triggered=cooldown_triggered,
        unrealised_warning=unrealised_warning,
        daily_loss_lock=daily_loss_lock,
    )


def _compute_discipline_score(
    realised_drawdown_pct: float,
    daily_loss_pct: float,
    consecutive_losses: int,
    is_locked: bool,
    params: dict,
) -> float:
    """Score 0–100. Penalises realised drawdown depth, daily loss ratio, streak, lock."""
    score = 100.0
    score -= min(40.0, (realised_drawdown_pct / DRAWDOWN_LOCKED) * 40.0)
    cap = params.get("daily_loss_cap", 0.02)
    score -= min(20.0, ((daily_loss_pct / cap) * 20.0) if cap > 0 else 0.0)
    score -= min(25.0, consecutive_losses * 5.0)
    if is_locked:
        score -= 15.0
    return max(0.0, round(score, 2))


# ─── Helpers used in services ─────────────────────────────────────────────────

def get_risk_params(mode: RiskMode) -> dict:
    return RISK_PARAMS[mode]


def is_cooldown_active(cooldown_until: Optional[datetime]) -> bool:
    if cooldown_until is None:
        return False
    return datetime.now(timezone.utc) < cooldown_until


def check_exposure_breach(
    current_exposure_value: float,
    new_trade_exposure: float,
    total_equity: float,
    params: dict,
) -> bool:
    if total_equity <= 0:
        return True
    return ((current_exposure_value + new_trade_exposure) / total_equity) > params["exposure_cap"]


def check_daily_loss_breach(
    daily_loss_today: float,
    proposed_additional_loss: float,
    starting_equity: float,
    params: dict,
) -> bool:
    cap_value = params["daily_loss_cap"] * starting_equity
    return (daily_loss_today + proposed_additional_loss) > cap_value

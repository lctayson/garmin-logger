"""Compact, conservative next-session recommendation from plan and recovery data."""
from __future__ import annotations

import datetime
import re
from typing import Any

_MONTHS = {name: number for number, name in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1
)}
_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _plan_week(context: str, target: datetime.date) -> str | None:
    marker = "# BHM 2027 Training Plan"
    if marker not in context:
        return None
    plan = context.split(marker, 1)[1]
    matches = list(re.finditer(r"(?m)^## W\d+ · ([A-Za-z]{3}) (\d{1,2}) ·[^\n]*", plan))
    for i, match in enumerate(matches):
        month, day = match.group(1), int(match.group(2))
        if month not in _MONTHS:
            continue
        year = 2027 if month in ("Jan", "Feb") else 2026
        try:
            start = datetime.date(year, _MONTHS[month], day)
        except ValueError:
            continue
        end = matches[i + 1].start() if i + 1 < len(matches) else len(plan)
        if start <= target <= start + datetime.timedelta(days=6):
            return plan[match.start():end]
    return None


def _next_plan_session(context: str, date_str: str) -> tuple[str, str] | None:
    try:
        today = datetime.date.fromisoformat(date_str)
    except (TypeError, ValueError):
        return None
    # Search the current and following plan weeks, stopping at the first
    # explicitly scheduled running session. Strength/rest-only days are skipped.
    for offset in range(1, 15):
        day = today + datetime.timedelta(days=offset)
        week = _plan_week(context, day)
        if not week:
            continue
        day_name = _DAYS[day.weekday()]
        pattern = rf"(?m)^- \*\*{day_name}(?: [^*]+)?\*\* (.+)$"
        match = re.search(pattern, week)
        if not match:
            continue
        prescription = match.group(1).strip()
        if re.search(r"\b(rest|strength|core)\b", prescription, re.IGNORECASE) and not re.search(
            r"\b(run|km|K|race|EZ|LSD|SUT|strides|hills|VO2|threshold|jog)\b", prescription, re.IGNORECASE
        ):
            continue
        return day.strftime("%a %b %-d"), prescription
    return None


def build_next_session_recommendation(
    metrics: dict[str, Any] | None, date_str: str, context: str
) -> dict[str, str] | None:
    """Return a concise decision, scheduled session, reason, and action."""
    if not isinstance(metrics, dict):
        return None
    scheduled = _next_plan_session(context, date_str)
    if not scheduled:
        return None
    session_date, prescription = scheduled
    readiness = metrics.get("readiness") or {}
    load = metrics.get("load") or {}
    summary = metrics.get("summary") or {}
    recovery = summary.get("recovery_trends") or {}
    score = _number(readiness.get("score"))
    sleep = _number(readiness.get("sleep_hours"))
    rhr_trend = recovery.get("resting_hr_trend")
    hrv_trend = recovery.get("hrv_trend")
    recovery_hours = _number(readiness.get("recovery_hours"))
    acwr_status = str(load.get("acwr_status") or "").lower()
    level = str(readiness.get("level") or "").lower()

    hard_session = bool(re.search(r"SUT|threshold|VO2|\b[3456]×|\b[234]×\dK|\btest\b|race", prescription, re.I))
    adverse = []
    if score is not None and score <= 25:
        adverse.append("very low Garmin readiness")
    if sleep is not None and sleep < 5:
        adverse.append(f"only {sleep:g} h sleep")
    if rhr_trend == "rising":
        adverse.append("recent resting-HR trend is rising")
    if hrv_trend == "falling":
        adverse.append("recent HRV trend is falling")
    if acwr_status in ("high", "very high", "strained"):
        adverse.append(f"Garmin load status is {load.get('acwr_status')}")
    if recovery_hours is not None and recovery_hours >= 36:
        adverse.append(f"{recovery_hours:g} h Garmin recovery time remains")

    # Require multiple independent warning signals before advising rest.
    if len(adverse) >= 3 and (hard_session or score is not None and score <= 20):
        decision = "PRIORITIZE RECOVERY"
        reason = "; ".join(adverse[:3]) + "."
        action = "Replace the planned run with rest or very easy, short running only if you feel well; reassess before the next quality session."
    elif len(adverse) >= 2 and hard_session:
        decision = "ADJUST THE WORKOUT"
        reason = "; ".join(adverse[:3]) + "."
        action = "Keep the session easy instead of doing the quality set, or reduce work repetitions by about one-third if symptoms are absent and warm-up feels normal."
    else:
        decision = "PROCEED AS PLANNED"
        evidence = []
        if score is not None:
            evidence.append(f"readiness {score:g}/100")
        if sleep is not None:
            evidence.append(f"sleep {sleep:g} h")
        if recovery_hours is not None:
            evidence.append(f"Garmin recovery {recovery_hours:g} h")
        reason = ("Available indicators do not show a strong combined recovery warning" +
                  (f" ({', '.join(evidence)})" if evidence else "") +
                  "; one metric alone is not enough to cancel training.")
        action = "Follow the prescribed distance, effort, and recoveries. If illness, significant pain, or unusual fatigue is present, do not push through it."

    return {
        "decision": decision,
        "session": f"{session_date} — {prescription}",
        "reason": reason,
        "action": action,
    }


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

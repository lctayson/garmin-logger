"""Derive an at-a-glance summary block from the compacted metrics payload.

Everything here is computed from values already present in the payload -- no
API calls, no new data. The point is that any reader (human or model) starts
from conclusions instead of re-deriving the same arithmetic every day, and
gets the *same* conclusions each time rather than whatever happens to be
noticed on a given pass.
"""
from __future__ import annotations

from typing import Any

SCHEMA_VERSION = 1

# Factors scoring at or below this are called out as holding readiness back.
_LIMITER_THRESHOLD = 70


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _col(trend: Any, name: str) -> list[Any]:
    """Pull one column out of a columnar {columns: [...], data: [[...]]} trend."""
    if not isinstance(trend, dict):
        return []
    columns = trend.get("columns")
    rows = trend.get("data")
    if not isinstance(columns, list) or not isinstance(rows, list):
        return []
    if name not in columns:
        return []
    idx = columns.index(name)
    return [row[idx] if isinstance(row, list) and len(row) > idx else None for row in rows]


def _avg(values: list[Any], places: int = 1) -> float | None:
    nums = [n for n in (_num(v) for v in values) if n is not None]
    if not nums:
        return None
    return round(sum(nums) / len(nums), places)


def _trend_direction(values: list[Any], tolerance: float = 0.0) -> str | None:
    """Compare the mean of the latter half of a series against the former half."""
    nums = [n for n in (_num(v) for v in values) if n is not None]
    if len(nums) < 4:
        return None
    half = len(nums) // 2
    first, second = nums[:half], nums[half:]
    delta = (sum(second) / len(second)) - (sum(first) / len(first))
    if abs(delta) <= tolerance:
        return "flat"
    return "rising" if delta > 0 else "falling"


def _readiness_summary(readiness: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("score", "level"):
        if readiness.get(key) is not None:
            out[key] = readiness[key]

    factors = readiness.get("factor_details")
    if isinstance(factors, dict):
        scored = {
            name: _num(value.get("percent"))
            for name, value in factors.items()
            if isinstance(value, dict) and _num(value.get("percent")) is not None
        }
        if scored:
            # The limiter is the single lowest-scoring factor; "limiting_factors"
            # lists every factor under the threshold, since more than one is
            # often soft at the same time and the runner-up matters too.
            limiter = min(scored, key=lambda k: scored[k])
            out["limiting_factor"] = limiter
            out["limiting_factor_percent"] = int(scored[limiter])
            soft = sorted((n for n, p in scored.items() if p <= _LIMITER_THRESHOLD), key=lambda n: scored[n])
            if soft:
                out["limiting_factors"] = soft
            strong = [n for n, p in scored.items() if p >= 95]
            if strong:
                out["strongest_factors"] = sorted(strong, key=lambda n: -scored[n])
    return out


def _load_summary(load: dict[str, Any], balance: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("acwr", "acwr_status", "training_status"):
        if load.get(key) is not None:
            out[key] = load[key]

    # Distance from target for each load-balance bucket. Negative = shortfall,
    # positive = over the ceiling, 0 = inside the target band. This is the
    # arithmetic that otherwise gets redone by eye every single day.
    gaps: dict[str, Any] = {}
    for name in ("aerobic_low", "aerobic_high", "anaerobic"):
        value = _num(balance.get(name))
        target = balance.get(f"{name}_target")
        if value is None or not isinstance(target, list) or len(target) != 2:
            continue
        lo, hi = _num(target[0]), _num(target[1])
        if lo is not None and value < lo:
            gaps[name] = {"gap": round(value - lo, 1), "state": "below_target"}
        elif hi is not None and value > hi:
            gaps[name] = {"gap": round(value - hi, 1), "state": "above_target"}
        else:
            gaps[name] = {"gap": 0, "state": "in_target"}
    if gaps:
        out["load_balance_gaps"] = gaps
    if balance.get("load_focus") is not None:
        out["load_focus"] = balance["load_focus"]
    return out


def _recovery_summary(payload: dict[str, Any], readiness: dict[str, Any]) -> dict[str, Any]:
    """Short-window trends that only exist by looking across days, not at today."""
    daily = payload.get("trend_recent_daily")
    out: dict[str, Any] = {}

    sleep_hours = _col(daily, "sleep_hours")
    if sleep_hours:
        out["sleep_7d_avg_h"] = _avg(sleep_hours, 2)
        need = _num((payload.get("sleep") or {}).get("need_h"))
        if need is not None:
            short = [n for n in (_num(v) for v in sleep_hours) if n is not None and n < need]
            out["sleep_nights_below_need"] = len(short)
            out["sleep_need_h"] = need
        direction = _trend_direction(sleep_hours, tolerance=0.25)
        if direction:
            out["sleep_trend"] = direction

    rhr = _col(daily, "resting_hr")
    if rhr:
        out["resting_hr_7d_avg"] = _avg(rhr)
        direction = _trend_direction(rhr, tolerance=0.5)
        if direction:
            # Rising RHR is the adverse direction, unlike rising HRV.
            out["resting_hr_trend"] = direction

    hrv_nightly = _col(daily, "hrv_last_night_avg_ms")
    if hrv_nightly:
        direction = _trend_direction(hrv_nightly, tolerance=1.0)
        if direction:
            out["hrv_trend"] = direction

    # Whether last night's HRV actually sits inside Garmin's balanced band.
    # The status string can lag the raw number when the band itself shifts,
    # so compare the value against the band directly.
    baseline = readiness.get("hrv_baseline")
    last_night = _num(readiness.get("hrv_last_night_avg_ms"))
    if isinstance(baseline, dict) and last_night is not None:
        lo = _num(baseline.get("balancedLow", baseline.get("balanced_low")))
        hi = _num(baseline.get("balancedUpper", baseline.get("balanced_upper")))
        if lo is not None and hi is not None:
            if last_night < lo:
                out["hrv_vs_balanced_band"] = "below"
            elif last_night > hi:
                out["hrv_vs_balanced_band"] = "above"
            else:
                out["hrv_vs_balanced_band"] = "within"
    return out


def _volume_summary(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    history = payload.get("training_history")
    if isinstance(history, dict):
        seven = ((history.get("7_day") or {}).get("total_endurance") or {})
        distance = _num(seven.get("distance"))
        if distance is not None:
            out["distance_7d_km"] = distance
        avg28 = _num((history.get("28_day") or {}).get("avg_weekly_running_distance"))
        if avg28 is not None:
            out["avg_weekly_distance_28d_km"] = avg28
            if distance is not None and avg28:
                out["distance_7d_vs_28d_avg_pct"] = round((distance / avg28 - 1) * 100, 1)

    tolerance = payload.get("running_tolerance")
    if isinstance(tolerance, dict):
        for old, new in (("percent_of_tolerance", "percent_of_tolerance"), ("status", "tolerance_status")):
            if tolerance.get(old) is not None:
                out[new] = tolerance[old]
    return out


def build_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Build the derived summary block for an already-compacted metrics payload."""
    if not isinstance(payload, dict):
        raise TypeError("metrics payload must be a dictionary")

    readiness = payload.get("readiness") or {}
    load = payload.get("load") or {}
    balance = payload.get("load_balance") or {}

    summary: dict[str, Any] = {"schema_version": SCHEMA_VERSION}
    if payload.get("date") is not None:
        summary["date"] = payload["date"]

    for name, section in (
        ("readiness", _readiness_summary(readiness)),
        ("load", _load_summary(load, balance)),
        ("recovery_trends", _recovery_summary(payload, readiness)),
        ("volume", _volume_summary(payload)),
    ):
        if section:
            summary[name] = section
    return summary


def attach_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Return payload with the summary block inserted directly after "date"."""
    summary = build_summary(payload)
    out: dict[str, Any] = {}
    if "date" in payload:
        out["date"] = payload["date"]
    out["summary"] = summary
    for key, value in payload.items():
        if key not in out:
            out[key] = value
    return out

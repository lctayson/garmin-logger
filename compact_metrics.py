"""Compact Garmin metrics JSON without removing analysis-critical information."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_DROP_TREND_COLUMNS = {
    "window_start",
    "window_end",
    "window_days",
    "acwr_status",
}


def _compact_factors(factors: Any) -> dict[str, Any] | None:
    if not isinstance(factors, dict):
        return None
    out = {}
    for key, value in factors.items():
        if isinstance(value, dict) and "percent" in value:
            out[key] = value.get("percent")
        elif value is not None:
            out[key] = value
    return out or None


def _compact_trend(trend: Any) -> Any:
    """Keep the existing column+row representation, removing derivable metadata."""
    if not isinstance(trend, dict):
        return trend
    columns = trend.get("columns")
    rows = trend.get("data")
    if not isinstance(columns, list) or not isinstance(rows, list):
        return trend

    keep = [i for i, column in enumerate(columns) if column not in _DROP_TREND_COLUMNS]
    new_columns = [columns[i] for i in keep]
    new_rows = []
    for row in rows:
        if isinstance(row, list):
            new_rows.append([row[i] if i < len(row) else None for i in keep])
        else:
            new_rows.append(row)
    return {"columns": new_columns, "data": new_rows}


def _compact_training_history(history: Any) -> dict[str, Any] | Any:
    if not isinstance(history, dict):
        return history

    out = dict(history)
    # This was retained for backward compatibility but is completely derivable
    # from 7_day.sports.running and 28_day.weekly_total_endurance.
    out.pop("legacy_running_summary", None)
    return out


def compact_metrics(data: dict[str, Any]) -> dict[str, Any]:
    """Return a smaller, analysis-friendly canonical metrics structure.

    The transformation removes duplicate/legacy representations while keeping
    the information needed for training, recovery, load and trend analysis.
    Unknown top-level fields are preserved so future Garmin additions are not
    silently discarded.
    """
    if not isinstance(data, dict):
        raise TypeError("metrics data must be a dictionary")

    source = dict(data)
    out: dict[str, Any] = {"date": source.get("date")}

    daily = source.get("daily_readiness") or {}
    health = source.get("health_stats") or {}
    status = source.get("training_status") or {}

    # Canonical readiness snapshot. Values duplicated elsewhere are kept here
    # once, using names that remain understandable to downstream analysis.
    readiness: dict[str, Any] = {}
    for key in (
        "score", "level", "feedback_short", "resting_hr", "hrv_last_night_avg_ms",
        "sleep_hours", "sleep_score", "recovery_hours",
    ):
        if key in daily and daily[key] is not None:
            readiness[key] = daily[key]
    if not readiness.get("resting_hr") and health.get("resting_hr") is not None:
        readiness["resting_hr"] = health["resting_hr"]
    if not readiness.get("hrv_last_night_avg_ms") and health.get("hrv", {}).get("last_night_avg_ms") is not None:
        readiness["hrv_last_night_avg_ms"] = health["hrv"]["last_night_avg_ms"]
    if not readiness.get("sleep_hours") and health.get("sleep_hours") is not None:
        readiness["sleep_hours"] = health["sleep_hours"]
    if not readiness.get("sleep_score") and health.get("sleep_score") is not None:
        readiness["sleep_score"] = health["sleep_score"]
    if daily.get("hrv_status") is not None:
        readiness["hrv_status"] = daily["hrv_status"]
    elif health.get("hrv", {}).get("status") is not None:
        readiness["hrv_status"] = health["hrv"]["status"]
    if daily.get("hrv_7_day_avg_ms") is not None:
        readiness["hrv_7_day_avg_ms"] = daily["hrv_7_day_avg_ms"]
    elif health.get("hrv", {}).get("seven_day_avg_ms") is not None:
        readiness["hrv_7_day_avg_ms"] = health["hrv"]["seven_day_avg_ms"]

    factors = _compact_factors((daily.get("readiness") or {}).get("factors"))
    if factors:
        readiness["factor_pct"] = factors
    if readiness:
        out["readiness"] = readiness

    # Sleep detail is useful for coaching, but the duplicate total sleep value
    # is intentionally omitted because it already exists in readiness.
    sleep: dict[str, Any] = {}
    stages = health.get("sleep_stages_hours")
    if isinstance(stages, dict):
        for key, value in stages.items():
            if value is not None:
                sleep[f"{key}_h"] = value
    need = daily.get("sleep_need") or {}
    for old, new in (("baseline_hours", "baseline_h"), ("need_hours", "need_h"), ("next_need_hours", "next_need_h")):
        if need.get(old) is not None:
            sleep[new] = need[old]
    if sleep:
        out["sleep"] = sleep

    # Canonical training/load snapshot. Keep the useful monthly load balance
    # because it cannot be reconstructed from the 7-day history.
    load = {}
    tl = status.get("training_load") or {}
    for old, new in (
        ("acute_load", "acute"),
        ("chronic_load", "chronic"),
        ("acwr", "acwr"),
        ("acwr_percent", "acwr_percent"),
        ("acwr_status", "acwr_status"),
    ):
        if tl.get(old) is not None:
            load[new] = tl[old]
    for old, new in (("vo2_max", "vo2max"), ("status", "status"), ("load_focus", "focus")):
        value = status.get(old)
        if value is not None:
            load[new] = value
    if load:
        out["load"] = load

    balance = status.get("monthly_load_balance")
    if isinstance(balance, dict):
        compact_balance = {}
        for name in ("aerobic_low", "aerobic_high", "anaerobic"):
            if name in balance:
                target_min = balance.get(f"{name}_target_min")
                target_max = balance.get(f"{name}_target_max")
                compact_balance[name] = balance[name]
                if target_min is not None or target_max is not None:
                    compact_balance[f"{name}_target"] = [target_min, target_max]
        if compact_balance:
            out["load_balance"] = compact_balance

    # Acclimation is small and useful; omit an inactive altitude record.
    heat = status.get("heat_acclimation")
    if isinstance(heat, dict) and heat:
        out["heat_acclimation"] = heat
    altitude = status.get("altitude_acclimation")
    if isinstance(altitude, dict) and (altitude.get("percentage") or altitude.get("trend")):
        out["altitude_acclimation"] = altitude

    history = _compact_training_history(source.get("training_history"))
    if isinstance(history, dict):
        out["training_history"] = history

    # Preserve trend arrays but remove repeated metadata that is derivable from
    # the row position/date and the ACWR value itself.
    for key in ("trend_recent_daily", "trend_long_range_weekly", "body_battery_trend"):
        if key in source:
            out[key] = _compact_trend(source[key])

    # Preserve additional current fields (for example running_tolerance) that
    # are not part of the canonical sections above.
    known = {
        "date", "daily_readiness", "health_stats", "training_status",
        "training_history", "trend_recent_daily", "trend_long_range_weekly",
        "body_battery_trend", "legacy_running_summary",
    }
    for key, value in source.items():
        if key not in known and key not in out:
            out[key] = value

    return out


def compact_file(path: str | Path) -> bool:
    """Compact one JSON file in place. Return True when it changed."""
    file_path = Path(path)
    original = file_path.read_text(encoding="utf-8")
    data = json.loads(original)
    compacted = json.dumps(compact_metrics(data), ensure_ascii=False, indent=2) + "\n"
    if compacted == original:
        return False
    file_path.write_text(compacted, encoding="utf-8")
    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Compact a Garmin metrics JSON file")
    parser.add_argument("path", nargs="?", default="data/latest_metrics.json")
    args = parser.parse_args()
    changed = compact_file(args.path)
    print(f"Compacted {args.path}" if changed else f"Already compact: {args.path}")

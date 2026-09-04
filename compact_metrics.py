"""Compact Garmin metrics JSON without removing analysis-critical information."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_DROP_TREND_COLUMNS = {"window_start", "window_end", "window_days", "acwr_status"}


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
    if not isinstance(trend, dict):
        return trend
    columns, rows = trend.get("columns"), trend.get("data")
    if not isinstance(columns, list) or not isinstance(rows, list):
        return trend
    keep = [i for i, column in enumerate(columns) if column not in _DROP_TREND_COLUMNS]
    return {
        "columns": [columns[i] for i in keep],
        "data": [
            [row[i] if i < len(row) else None for i in keep] if isinstance(row, list) else row
            for row in rows
        ],
    }


def _compact_training_history(history: Any) -> dict[str, Any] | Any:
    if not isinstance(history, dict):
        return history
    out = dict(history)
    out.pop("legacy_running_summary", None)
    return out


def compact_metrics(data: dict[str, Any]) -> dict[str, Any]:
    """Remove redundant representations while retaining coaching-relevant data."""
    if not isinstance(data, dict):
        raise TypeError("metrics data must be a dictionary")

    source = dict(data)
    out: dict[str, Any] = {"date": source.get("date")}
    daily = source.get("daily_readiness") or {}
    health = source.get("health_stats") or {}
    status = source.get("training_status") or {}

    readiness: dict[str, Any] = {}
    for key in ("score", "level", "feedback_short", "resting_hr", "hrv_last_night_avg_ms", "sleep_hours", "sleep_score", "recovery_hours"):
        if daily.get(key) is not None:
            readiness[key] = daily[key]
    if readiness.get("resting_hr") is None and health.get("resting_hr") is not None:
        readiness["resting_hr"] = health["resting_hr"]
    if readiness.get("hrv_last_night_avg_ms") is None and (health.get("hrv") or {}).get("last_night_avg_ms") is not None:
        readiness["hrv_last_night_avg_ms"] = health["hrv"]["last_night_avg_ms"]
    if readiness.get("sleep_hours") is None and health.get("sleep_hours") is not None:
        readiness["sleep_hours"] = health["sleep_hours"]
    if readiness.get("sleep_score") is None and health.get("sleep_score") is not None:
        readiness["sleep_score"] = health["sleep_score"]
    if daily.get("hrv_status") is not None:
        readiness["hrv_status"] = daily["hrv_status"]
    elif (health.get("hrv") or {}).get("status") is not None:
        readiness["hrv_status"] = health["hrv"]["status"]
    if daily.get("hrv_7_day_avg_ms") is not None:
        readiness["hrv_7_day_avg_ms"] = daily["hrv_7_day_avg_ms"]
    elif (health.get("hrv") or {}).get("7d_avg_ms") is not None:
        readiness["hrv_7_day_avg_ms"] = health["hrv"]["7d_avg_ms"]
    elif (health.get("hrv") or {}).get("seven_day_avg_ms") is not None:
        readiness["hrv_7_day_avg_ms"] = health["hrv"]["seven_day_avg_ms"]
    baseline = (health.get("hrv") or {}).get("baseline_balanced_range")
    if baseline:
        readiness["hrv_baseline"] = baseline
    factors = _compact_factors((daily.get("readiness") or {}).get("factors"))
    if factors:
        readiness["factor_pct"] = factors
    if readiness:
        out["readiness"] = readiness

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
    if daily.get("previous_day_nap") is not None:
        sleep["previous_day_nap"] = daily["previous_day_nap"]
    if health.get("steps") is not None:
        sleep["steps"] = health["steps"]
    if sleep:
        out["sleep"] = sleep

    load: dict[str, Any] = {}
    tl = status.get("training_load") or {}
    for old, new in (("acute_load", "acute"), ("chronic_load", "chronic"), ("acwr", "acwr"), ("acwr_percent", "acwr_percent"), ("acwr_status", "acwr_status")):
        if tl.get(old) is not None:
            load[new] = tl[old]
    if tl.get("chronic_load_range") is not None:
        load["chronic_range"] = tl["chronic_load_range"]
    for old, new in (("vo2_max", "vo2max"), ("status", "status"), ("load_focus", "focus")):
        if status.get(old) is not None:
            load[new] = status[old]
    if load:
        out["load"] = load

    balance = status.get("monthly_load_balance")
    if isinstance(balance, dict):
        compact_balance = {}
        for name in ("aerobic_low", "aerobic_high", "anaerobic"):
            if name in balance:
                compact_balance[name] = balance[name]
                lo, hi = balance.get(f"{name}_target_min"), balance.get(f"{name}_target_max")
                if lo is not None or hi is not None:
                    compact_balance[f"{name}_target"] = [lo, hi]
        if compact_balance:
            out["load_balance"] = compact_balance

    heat = status.get("heat_acclimation")
    if isinstance(heat, dict) and heat:
        out["heat_acclimation"] = heat
    altitude = status.get("altitude_acclimation")
    if isinstance(altitude, dict) and (altitude.get("percentage") or altitude.get("trend")):
        out["altitude_acclimation"] = altitude

    history = _compact_training_history(source.get("training_history"))
    if isinstance(history, dict):
        out["training_history"] = history

    for key in ("trend_recent_daily", "trend_long_range_weekly", "body_battery_trend"):
        if key in source:
            out[key] = _compact_trend(source[key])

    known = {"date", "daily_readiness", "health_stats", "training_status", "training_history", "trend_recent_daily", "trend_long_range_weekly", "body_battery_trend", "legacy_running_summary"}
    for key, value in source.items():
        if key not in known and key not in out:
            out[key] = value
    return out


def compact_file(path: str | Path) -> bool:
    """Compact one JSON file in place. Return True when it changed."""
    file_path = Path(path)
    original = file_path.read_text(encoding="utf-8")
    compacted = json.dumps(compact_metrics(json.loads(original)), ensure_ascii=False, indent=2) + "\n"
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

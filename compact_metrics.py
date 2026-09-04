"""Build the canonical, analysis-friendly Garmin metrics JSON."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DROP_TREND_COLUMNS = {"window_start", "window_end", "window_days", "acwr_status"}
_ACTIVITY_KEYS = {"activities", "activity_data", "activityData"}
_TREND_KEYS = ("trend_recent_daily", "trend_long_range_weekly", "body_battery_trend")


def _compact_factors(factors: Any) -> dict[str, Any] | None:
    if not isinstance(factors, dict):
        return None
    out: dict[str, Any] = {}
    for key, value in factors.items():
        if isinstance(value, dict):
            item: dict[str, Any] = {}
            if value.get("percent") is not None:
                item["percent"] = value["percent"]
            if value.get("feedback") is not None:
                item["feedback"] = value["feedback"]
            out[key] = item or value
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


def compact_metrics(source: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw/intermediate Garmin payload into one canonical metrics shape."""
    if not isinstance(source, dict):
        raise TypeError("metrics data must be a dictionary")

    # Protect against accidentally running this helper on an already-canonical file.
    if "readiness" in source and "daily_readiness" not in source:
        out = dict(source)
        for key in _TREND_KEYS:
            if key in out:
                out[key] = _compact_trend(out[key])
        return out

    out: dict[str, Any] = {}
    if source.get("date") is not None:
        out["date"] = source["date"]

    daily = source.get("daily_readiness") or {}
    health = source.get("health_stats") or {}
    status = source.get("training_status") or {}

    readiness: dict[str, Any] = {}
    direct = (
        ("score", "score"),
        ("level", "level"),
        ("feedback_short", "feedback"),
        ("resting_hr", "resting_hr"),
        ("hrv_last_night_avg_ms", "hrv_last_night_avg_ms"),
        ("hrv_7_day_avg_ms", "hrv_7_day_avg_ms"),
        ("hrv_status", "hrv_status"),
        ("sleep_hours", "sleep_hours"),
        ("sleep_score", "sleep_score"),
        ("recovery_hours", "recovery_hours"),
    )
    for old, new in direct:
        if daily.get(old) is not None:
            readiness[new] = daily[old]

    hrv = health.get("hrv") or {}
    fallbacks = (
        ("resting_hr", health.get("resting_hr")),
        ("hrv_last_night_avg_ms", hrv.get("last_night_avg_ms")),
        ("hrv_7_day_avg_ms", hrv.get("7d_avg_ms", hrv.get("seven_day_avg_ms"))),
        ("hrv_status", hrv.get("status")),
        ("sleep_hours", health.get("sleep_hours")),
        ("sleep_score", health.get("sleep_score")),
    )
    for key, value in fallbacks:
        if readiness.get(key) is None and value is not None:
            readiness[key] = value

    baseline = hrv.get("baseline_balanced_range")
    if baseline:
        readiness["hrv_baseline"] = baseline
    factors = _compact_factors((daily.get("readiness") or {}).get("factors"))
    if factors:
        readiness["factor_details"] = factors
    if readiness:
        out["readiness"] = readiness

    sleep: dict[str, Any] = {}
    stages = health.get("sleep_stages_hours")
    if isinstance(stages, dict):
        for key, value in stages.items():
            if value is not None:
                sleep[f"{key}_h"] = value
    need = daily.get("sleep_need") or {}
    for old, new in (
        ("baseline_hours", "baseline_h"),
        ("need_hours", "need_h"),
        ("next_need_hours", "next_need_h"),
        ("feedback", "feedback"),
        ("training_feedback", "training_feedback"),
        ("sleep_history_adjustment", "sleep_history_adjustment"),
        ("hrv_adjustment", "hrv_adjustment"),
        ("nap_adjustment", "nap_adjustment"),
    ):
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
    for key in ("acute_load", "chronic_load", "acwr", "acwr_percent", "acwr_status"):
        if tl.get(key) is not None:
            load[key] = tl[key]
    if tl.get("chronic_load_range") is not None:
        load["chronic_load_range"] = tl["chronic_load_range"]
    for old, new in (("vo2_max", "vo2_max"), ("status", "training_status"), ("load_focus", "load_focus")):
        if status.get(old) is not None:
            load[new] = status[old]
    if load:
        out["load"] = load

    balance = status.get("monthly_load_balance")
    if isinstance(balance, dict):
        compact_balance: dict[str, Any] = {}
        for name in ("aerobic_low", "aerobic_high", "anaerobic"):
            if name in balance:
                compact_balance[name] = balance[name]
                lo = balance.get(f"{name}_target_min")
                hi = balance.get(f"{name}_target_max")
                if lo is not None or hi is not None:
                    compact_balance[f"{name}_target"] = [lo, hi]
        if compact_balance:
            out["load_balance"] = compact_balance

    for key in ("heat_acclimation", "altitude_acclimation"):
        value = status.get(key)
        if isinstance(value, dict) and value:
            out[key] = value

    history = source.get("training_history")
    if isinstance(history, dict):
        history = dict(history)
        history.pop("legacy_running_summary", None)
        out["training_history"] = history

    for key in _TREND_KEYS:
        if key in source:
            out[key] = _compact_trend(source[key])

    # Preserve genuinely new top-level metrics rather than silently dropping them.
    known = {"date", "daily_readiness", "health_stats", "training_status", "training_history", "legacy_running_summary"} | set(_TREND_KEYS) | _ACTIVITY_KEYS
    for key, value in source.items():
        if key not in known and key not in out:
            out[key] = value
    return out


def compact_file(path: str | Path) -> bool:
    """Compact one JSON file in place; the normal pipeline calls compact_metrics in memory."""
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
    print(f"Compacted {args.path}" if changed else f"Already canonical: {args.path}")

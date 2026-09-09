"""Run the normal Garmin JSON generator with API-based enrichment."""
import argparse
import sys

import garmin_to_json as generator
from activity_zones import add_activity_zones
from garmin_activity_enrichment import enrich_activity, _running_tolerance
from activity_units import apply_user_units
from recovery_hr import add_recovery_hr
from config import get_timezone, resolve_timezone

_original_get_activities = generator.get_activities
_original_get_training_history = generator.get_training_history

def _add_activity_recovery_hr(api, activity):
    """Copy Garmin's stored two-minute recovery-HR drop when available."""
    if not isinstance(activity, dict) or not activity.get("activityId"):
        return activity
    try:
        detail = api.get_activity(activity["activityId"]) or {}
    except Exception:
        return activity
    summary = detail.get("summaryDTO", {}) if isinstance(detail, dict) else {}
    if not isinstance(summary, dict):
        summary = {}
    value = summary.get("recoveryHeartRate")
    if value is None and isinstance(detail, dict):
        value = detail.get("recoveryHeartRate")
    if value is not None:
        try:
            activity["recovery_hr"] = round(float(value))
        except (TypeError, ValueError):
            pass
    return activity

def _format_time(seconds):
    if seconds is None:
        return None
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        return None
    if total < 0:
        return None
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"

def _split_duration_seconds(split):
    """Return split duration in seconds from raw seconds or formatted time."""
    value = split.get("time_seconds") if isinstance(split, dict) else None
    if value is not None:
        try:
            return float(value)
        except (TypeError, ValueError):
            pass
    text = split.get("time") if isinstance(split, dict) else None
    if isinstance(text, str) and ":" in text:
        try:
            minutes, seconds = text.split(":", 1)
            return float(minutes) * 60.0 + float(seconds)
        except (TypeError, ValueError):
            pass
    return None

def _normalize_training_effect_message(value):
    if not isinstance(value, str) or not value:
        return None
    parts = value.split("_")
    if len(parts) > 1 and parts[-1].isdigit():
        return "_".join(parts[:-1])
    return value

def _find_nested_value(source, keys):
    """Find the first non-empty value for any key recursively."""
    if isinstance(source, dict):
        for key in keys:
            value = source.get(key)
            if value is not None and value != "":
                return value
        for value in source.values():
            found = _find_nested_value(value, keys)
            if found is not None:
                return found
    elif isinstance(source, list):
        for value in source:
            found = _find_nested_value(value, keys)
            if found is not None:
                return found
    return None

def _add_interval_drift(activity):
    """Add interval-to-interval drift metrics from Garmin lap splits."""
    if not isinstance(activity, dict) or str(activity.get("type", "")).lower() != "running":
        return activity

    splits = activity.get("activity_splits")
    if not isinstance(splits, list) or not splits:
        split_table = activity.get("splits")
        if isinstance(split_table, dict) and isinstance(split_table.get("columns"), list) and isinstance(split_table.get("data"), list):
            columns = split_table["columns"]
            splits = [dict(zip(columns, row)) for row in split_table["data"] if isinstance(row, list)]
    if not isinstance(splits, list) or not splits:
        return activity

    work = []
    for split in splits:
        if not isinstance(split, dict) or str(split.get("step_type", "")).upper() != "ACTIVE":
            continue
        seconds = _split_duration_seconds(split)
        if seconds is None or seconds < 120:
            continue
        if split.get("avg_pace") is None or split.get("avg_hr") is None:
            continue
        work.append(split)

    if len(work) < 2:
        return activity

    def pace_seconds(value):
        if not isinstance(value, str) or ":" not in value:
            return None
        try:
            minutes, seconds = value.split(":", 1)
            total = float(minutes) * 60.0 + float(seconds)
            return total if total > 0 else None
        except (TypeError, ValueError):
            return None

    first = work[0]
    last = work[-1]
    first_pace = pace_seconds(first.get("avg_pace"))
    last_pace = pace_seconds(last.get("avg_pace"))
    try:
        first_hr = float(first.get("avg_hr"))
        last_hr = float(last.get("avg_hr"))
    except (TypeError, ValueError):
        return activity
    if first_pace is None or last_pace is None or first_hr <= 0 or last_hr <= 0:
        return activity

    first_ef = (1.0 / first_pace) / first_hr
    last_ef = (1.0 / last_pace) / last_hr
    pace_drift = (last_ef / first_ef - 1.0) * 100.0

    result = {
        "work_reps": len(work),
        "pace_ef_drift_pct": round(pace_drift, 1),
        "hr_delta_bpm": round(last_hr - first_hr, 1),
    }

    try:
        first_power = float(first.get("avg_power_w"))
        last_power = float(last.get("avg_power_w"))
    except (TypeError, ValueError):
        first_power = last_power = None
    if first_power is not None and last_power is not None and first_power > 0:
        first_power_ef = first_power / first_hr
        last_power_ef = last_power / last_hr
        result["power_ef_drift_pct"] = round((last_power_ef / first_power_ef - 1.0) * 100.0, 1)
        result["power_delta_w"] = round(last_power - first_power, 1)

    activity["interval_drift"] = result
    return activity

def _add_activity_detail_fields(api, activity):
    """Add high-value Garmin detail fields without changing the raw exporter."""
    activity_id = activity.get("activityId")
    if not activity_id:
        return activity
    try:
        detail = api.get_activity(activity_id) or {}
    except Exception:
        detail = {}
    summary = detail.get("summaryDTO", {}) if isinstance(detail, dict) else {}
    if not isinstance(summary, dict):
        summary = {}
    def first(*values):
        for value in values:
            if value is not None and value != "":
                return value
        return None
    duration = first(summary.get("duration"), detail.get("duration"), activity.get("duration"))
    elapsed = first(summary.get("elapsedDuration"), detail.get("elapsedDuration"), duration)
    moving = first(summary.get("movingDuration"), detail.get("movingDuration"), duration)
    if duration is not None:
        activity["time"] = _format_time(duration)
    if elapsed is not None:
        activity["elapsed_time"] = _format_time(elapsed)
    if moving is not None:
        activity["moving_time"] = _format_time(moving)
    label = first(summary.get("trainingEffectLabel"), detail.get("trainingEffectLabel"))
    aerobic = first(summary.get("aerobicTrainingEffect"), detail.get("aerobicTrainingEffect"), activity.get("aerobic_te"))
    anaerobic = first(summary.get("anaerobicTrainingEffect"), detail.get("anaerobicTrainingEffect"), activity.get("anaerobic_te"))
    aerobic_message = first(summary.get("aerobicTrainingEffectMessage"), detail.get("aerobicTrainingEffectMessage"))
    anaerobic_message = first(summary.get("anaerobicTrainingEffectMessage"), detail.get("anaerobicTrainingEffectMessage"))
    training_effect = {
        "label": label,
        "aerobic": float(aerobic) if aerobic is not None else None,
        "aerobic_message": _normalize_training_effect_message(aerobic_message),
        "anaerobic": float(anaerobic) if anaerobic is not None else None,
        "anaerobic_message": _normalize_training_effect_message(anaerobic_message),
    }
    training_effect = {k: v for k, v in training_effect.items() if v is not None}
    if training_effect:
        activity["training_effect"] = training_effect
    activity_vo2max = first(
        summary.get("vO2MaxValue"), summary.get("vo2MaxValue"),
        detail.get("vO2MaxValue"), detail.get("vo2MaxValue"),
        activity.get("vO2MaxValue"), activity.get("vo2MaxValue")
    )
    if activity_vo2max is None:
        activity_vo2max = _find_nested_value(detail, ("vO2MaxValue", "vo2MaxValue", "vo2MaxPreciseValue"))
    if activity_vo2max is None:
        activity_vo2max = _find_nested_value(activity, ("vO2MaxValue", "vo2MaxValue", "vo2MaxPreciseValue"))
    if activity_vo2max is not None:
        try:
            activity["activity_vo2max"] = float(activity_vo2max)
        except (TypeError, ValueError):
            pass
    lap_count = first(summary.get("lapCount"), detail.get("lapCount"), activity.get("lapCount"))
    if lap_count is None:
        try:
            split_payload = api.get_activity_splits(activity_id) or {}
            lap_dtos = split_payload.get("lapDTOs", []) if isinstance(split_payload, dict) else []
            lap_count = len(lap_dtos) if isinstance(lap_dtos, list) else None
        except Exception:
            lap_dtos = []
    else:
        lap_dtos = []
    if lap_count is not None:
        try:
            activity["lap_count"] = int(float(lap_count))
        except (TypeError, ValueError):
            pass
    splits = activity.get("activity_splits") or activity.get("splits")
    if isinstance(splits, dict) and isinstance(splits.get("columns"), list) and isinstance(splits.get("data"), list):
        columns = list(splits["columns"])
        rows = [list(row) if isinstance(row, list) else row for row in splits["data"]]
        if "elapsed_time" not in columns:
            if "time" in columns:
                insert_at = columns.index("time") + 1
            else:
                insert_at = len(columns)
            columns.insert(insert_at, "elapsed_time")
        else:
            insert_at = columns.index("elapsed_time")
        if not lap_dtos:
            try:
                split_payload = api.get_activity_splits(activity_id) or {}
                lap_dtos = split_payload.get("lapDTOs", []) if isinstance(split_payload, dict) else []
            except Exception:
                lap_dtos = []
        for index, row in enumerate(rows):
            if not isinstance(row, list) or index >= len(lap_dtos) or not isinstance(lap_dtos[index], dict):
                continue
            raw = lap_dtos[index].get("elapsedDuration")
            if raw is None:
                raw = lap_dtos[index].get("duration")
            if raw is None:
                continue
            elapsed_value = _format_time(raw)
            if insert_at < len(row):
                row[insert_at] = elapsed_value
            else:
                row.append(elapsed_value)
        splits["columns"] = columns
        splits["data"] = rows
        if "activity_splits" in activity:
            activity["activity_splits"] = splits
        else:
            activity["splits"] = splits
    return activity

def get_activities(api, target_date):
    date_str = target_date.isoformat() if hasattr(target_date, "isoformat") else str(target_date)
    activities = _original_get_activities(api, date_str)
    enriched = [enrich_activity(api, dict(a)) for a in activities or []]
    enriched = [_add_activity_detail_fields(api, a) for a in enriched]
    enriched = [_add_interval_drift(a) for a in enriched]
    enriched = [_add_activity_recovery_hr(api, a) for a in enriched]
    enriched = [add_recovery_hr(api, a) for a in enriched]
    enriched = add_activity_zones(api, enriched)
    return apply_user_units(api, enriched)

def get_training_history(api, target_date):
    history = _original_get_training_history(api, target_date)
    tolerance = _running_tolerance(api, target_date)
    if tolerance is not None:
        history["running_tolerance"] = tolerance
    return history

generator.get_activities = get_activities
generator.get_training_history = get_training_history

def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--timezone", help="IANA timezone override, e.g. America/New_York")
    args, remaining = parser.parse_known_args()
    timezone_name = resolve_timezone(args.timezone)
    generator.LOCAL_TZ = get_timezone(args.timezone)
    sys.argv = [sys.argv[0], *remaining]
    print(f"Using timezone: {timezone_name}")
    generator.main()

if __name__ == "__main__":
    main()

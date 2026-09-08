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


def _normalize_training_effect_message(value):
    if not isinstance(value, str) or not value:
        return None
    parts = value.split("_")
    if len(parts) > 1 and parts[-1].isdigit():
        return "_".join(parts[:-1])
    return value


def _insert_elapsed_after_time(row, elapsed_value):
    """Insert elapsed_time immediately after time while preserving all other fields."""
    if not isinstance(row, dict):
        return row
    ordered = {}
    for key, value in row.items():
        ordered[key] = value
        if key == "time":
            ordered["elapsed_time"] = elapsed_value
    if "elapsed_time" not in ordered:
        ordered["elapsed_time"] = elapsed_value
    return ordered


def _add_split_elapsed_times(api, activity):
    """Add Garmin lap elapsedDuration to every activity split."""
    splits = activity.get("activity_splits") or activity.get("splits")
    if not isinstance(splits, list):
        return
    activity_id = activity.get("activityId")
    if not activity_id:
        return
    try:
        split_payload = api.get_activity_splits(activity_id) or {}
        lap_dtos = split_payload.get("lapDTOs", []) if isinstance(split_payload, dict) else []
    except Exception:
        lap_dtos = []
    if not isinstance(lap_dtos, list):
        lap_dtos = []

    updated = []
    for index, row in enumerate(splits):
        if not isinstance(row, dict):
            updated.append(row)
            continue
        raw = None
        if index < len(lap_dtos) and isinstance(lap_dtos[index], dict):
            raw = lap_dtos[index].get("elapsedDuration")
            if raw is None:
                raw = lap_dtos[index].get("duration")
        if raw is None:
            raw = row.get("time")
            if isinstance(raw, str) and ":" in raw:
                minutes, seconds = raw.split(":", 1)
                try:
                    raw = float(minutes) * 60.0 + float(seconds)
                except ValueError:
                    raw = None
        elapsed_value = _format_time(raw)
        updated.append(_insert_elapsed_after_time(row, elapsed_value))
    activity["activity_splits"] = updated


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
    elapsed = first(summary.get("elapsedDuration"), detail.get("elapsedDuration"), activity.get("elapsedDuration"), duration)
    moving = first(summary.get("movingDuration"), detail.get("movingDuration"), activity.get("movingDuration"), duration)

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
        detail.get("vO2MaxValue"), detail.get("vo2MaxValue")
    )
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

    _add_split_elapsed_times(api, activity)

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
            elapsed_values = []
            if not lap_dtos:
                try:
                    split_payload = api.get_activity_splits(activity_id) or {}
                    lap_dtos = split_payload.get("lapDTOs", []) if isinstance(split_payload, dict) else []
                except Exception:
                    lap_dtos = []
            for index, row in enumerate(rows):
                elapsed_value = None
                if index < len(lap_dtos) and isinstance(lap_dtos[index], dict):
                    raw = lap_dtos[index].get("elapsedDuration")
                    if raw is None:
                        raw = lap_dtos[index].get("duration")
                    elapsed_value = _format_time(raw)
                elapsed_values.append(elapsed_value)
            for row, elapsed_value in zip(rows, elapsed_values):
                if isinstance(row, list):
                    row.insert(insert_at, elapsed_value)
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
    enriched = [_add_activity_recovery_hr(api, a) for a in enriched]
    enriched = [_add_activity_detail_fields(api, a) for a in enriched]
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

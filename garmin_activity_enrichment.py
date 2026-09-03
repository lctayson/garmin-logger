from collections import OrderedDict
from datetime import timedelta

import garmin_to_json as generator
from activity_zones import add_activity_zones


# Activity-split JSON order follows the user's Garmin Connect export header:
# important performance fields first, with pace/HR/mechanics grouped together.
SPLIT_COLUMN_ORDER = (
    "interval",
    "step_type",
    "lap",
    "time",
    "distance_km",
    "avg_pace",
    "avg_gap",
    "avg_hr",
    "max_hr",
    "elevation_gain_m",
    "elevation_loss_m",
    "avg_run_cadence",
    "avg_ground_contact_time_ms",
    "avg_stride_length_m",
    "avg_vertical_oscillation_cm",
    "avg_vertical_ratio_pct",
    "normalized_power_w",
    "avg_power_w",
    "avg_w_kg",
    "max_power_w",
    "max_w_kg",
    "calories",
    "best_pace",
    "max_run_cadence",
    "moving_time",
    "avg_moving_pace",
)


def _pace_from_speed(speed):
    try:
        speed = float(speed)
    except (TypeError, ValueError):
        return None
    if speed <= 0:
        return None
    sec = int(round(1000.0 / speed))
    return f"{sec // 60}:{sec % 60:02d}"


def _duration(seconds):
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        return None
    return f"{total // 60}:{total % 60:02d}" if total >= 0 else None


def _running_tolerance(api, target_date):
    get_rt = getattr(api, "get_running_tolerance", None)
    if not callable(get_rt):
        return None
    start = target_date - timedelta(days=6)
    try:
        rows = get_rt(start.isoformat(), target_date.isoformat(), aggregation="daily") or []
    except Exception:
        return None
    rows = [r for r in rows if isinstance(r, dict)]
    if not rows:
        return None
    latest = max(rows, key=lambda r: str(r.get("calendarDate") or r.get("date") or ""))
    acute = generator.deep_get(latest, ["totalImpactLoad", "acuteImpactLoad", "acute_impact_load"])
    tolerance = generator.deep_get(latest, ["tolerance", "runningTolerance", "weeklyTolerance"])
    if acute is None or tolerance is None:
        return None
    acute_km = generator.safe_float(acute, 1)
    tolerance_km = generator.safe_float(tolerance, 1)
    if acute_km is None or tolerance_km is None or tolerance_km <= 0:
        return None
    actual_7d_m = 0.0
    for row in rows:
        distance = generator.deep_get(row, ["totalDistance", "distance"])
        try:
            if distance is not None:
                actual_7d_m += float(distance)
        except (TypeError, ValueError):
            pass
    percent = round(acute_km / tolerance_km * 100.0, 1)
    status = "Exceeded" if percent > 100 else "High" if percent >= 75 else "Medium" if percent >= 50 else "Low"
    return {
        "acute_impact_load_km": acute_km,
        "weekly_tolerance_km": tolerance_km,
        "actual_7_day_distance_km": generator.safe_float(actual_7d_m / 1000.0, 1),
        "status": status,
        "percent_of_tolerance": percent,
    }


def _reorder_split(item):
    """Return a split using the requested Garmin Connect export ordering."""
    ordered = OrderedDict()
    for key in SPLIT_COLUMN_ORDER:
        if key in item and item[key] is not None:
            ordered[key] = item[key]

    # Preserve any genuinely supplied fields not in the display header.
    for key, value in item.items():
        if key not in ordered and value is not None:
            ordered[key] = value
    return dict(ordered)


def enrich_activity_splits(api, activity):
    activity_id = activity.get("activityId") if isinstance(activity, dict) else None
    if not activity_id:
        return
    try:
        raw = api.get_activity_splits(activity_id) or {}
    except Exception:
        return
    laps = raw.get("lapDTOs", []) if isinstance(raw, dict) else []
    existing = activity.get("activity_splits") or []
    if not isinstance(existing, list):
        existing = []
    by_lap = {
        x.get("lap"): x
        for x in existing
        if isinstance(x, dict) and x.get("lap") is not None
    }

    fields = (
        ("elevationGain", "elevation_gain_m", 1),
        ("elevationLoss", "elevation_loss_m", 1),
        ("averageHR", "avg_hr", 0),
        ("maxHR", "max_hr", 0),
        ("averageRunCadence", "avg_run_cadence", 0),
        ("groundContactTime", "avg_ground_contact_time_ms", 1),
        ("verticalOscillation", "avg_vertical_oscillation_cm", 1),
        ("verticalRatio", "avg_vertical_ratio_pct", 1),
        ("normalizedPower", "normalized_power_w", 0),
        ("averagePower", "avg_power_w", 0),
        ("maxPower", "max_power_w", 0),
        ("calories", "calories", 0),
    )

    for lap in laps:
        if not isinstance(lap, dict):
            continue
        lap_number = lap.get("lapIndex")
        item = by_lap.get(lap_number)
        if item is None:
            continue

        if lap.get("intensityType") is not None:
            item["step_type"] = lap["intensityType"]
        item.pop("intensity", None)
        item.pop("cumulative_time", None)

        pace = _pace_from_speed(lap.get("averageSpeed"))
        gap = _pace_from_speed(lap.get("avgGradeAdjustedSpeed"))
        if pace is not None:
            item["avg_pace"] = pace
        if gap is not None:
            item["avg_gap"] = gap

        duration_seconds = lap.get("duration")
        try:
            duration_seconds = float(duration_seconds) if duration_seconds is not None else 0.0
        except (TypeError, ValueError):
            duration_seconds = 0.0
        duration = _duration(duration_seconds)
        if duration is not None:
            item["time"] = duration

        if lap.get("distance") is not None:
            try:
                item["distance_km"] = round(float(lap["distance"]) / 1000.0, 2)
            except (TypeError, ValueError):
                pass

        for src, dst, decimals in fields:
            if lap.get(src) is not None:
                item[dst] = generator.safe_float(lap[src], decimals)

        if lap.get("strideLength") is not None:
            try:
                item["avg_stride_length_m"] = round(float(lap["strideLength"]) / 100.0, 2)
            except (TypeError, ValueError):
                pass

        if lap.get("averagePower") is not None and lap.get("weight") is not None:
            try:
                item["avg_w_kg"] = round(float(lap["averagePower"]) / float(lap["weight"]), 2)
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        if lap.get("maxPower") is not None and lap.get("weight") is not None:
            try:
                item["max_w_kg"] = round(float(lap["maxPower"]) / float(lap["weight"]), 2)
            except (TypeError, ValueError, ZeroDivisionError):
                pass

        moving_duration = lap.get("movingDuration")
        if moving_duration is not None:
            moving_time = _duration(moving_duration)
            if moving_time is not None:
                item["moving_time"] = moving_time

        moving_speed = lap.get("averageMovingSpeed")
        moving_pace = _pace_from_speed(moving_speed)
        if moving_pace is not None:
            item["avg_moving_pace"] = moving_pace

        max_speed = lap.get("maxSpeed")
        best_pace = _pace_from_speed(max_speed)
        if best_pace is not None:
            item["best_pace"] = best_pace

        max_cadence = lap.get("maxRunCadence")
        if max_cadence is not None:
            item["max_run_cadence"] = generator.safe_float(max_cadence, 0)

        item = _reorder_split(item)
        by_lap[lap_number] = item

    activity["activity_splits"] = list(by_lap.values())

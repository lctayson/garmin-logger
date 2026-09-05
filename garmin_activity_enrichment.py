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

# Garmin/base-generator names that duplicate the canonical split fields above.
# Remove them at the enrichment stage so every newly generated JSON file stays clean.
DUPLICATE_SPLIT_FIELDS = (
    "time_min",
    "moving_time_min",
    "cadence_spm",
    "max_cadence_spm",
    "ground_contact_ms",
    "vertical_oscillation_cm",
    "vertical_ratio_pct",
    "avg_gct_ms",
    "avg_stride_length_m",  # canonical output is normalized to stride_length_m later
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

        # Remove duplicate/legacy names before writing the canonical names.
        # This is intentionally done in the generator, not by post-processing
        # an already-generated JSON file.
        for key in DUPLICATE_SPLIT_FIELDS:
            item.pop(key, None)

        if lap.get("intensityType") is not None:
            item["step_type"] = lap["intensityType"]
        item.pop("intensity", None)
        item.pop("cumulative_time", None)
        item.pop("cumulative_time_min", None)
        item.pop("intensityType", None)

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

        moving_pace = _pace_from_speed(lap.get("averageMovingSpeed"))
        if moving_pace is not None:
            item["avg_moving_pace"] = moving_pace

        best_pace = _pace_from_speed(lap.get("maxSpeed"))
        if best_pace is not None:
            item["best_pace"] = best_pace

        if lap.get("maxRunCadence") is not None:
            item["max_run_cadence"] = generator.safe_float(lap["maxRunCadence"], 0)

        by_lap[lap_number] = _reorder_split(item)

    activity["activity_splits"] = list(by_lap.values())


def _get_user_unit_system(api):
    """Return Garmin's account measurement system without making another API call."""
    get_unit_system = getattr(api, "get_unit_system", None)
    if callable(get_unit_system):
        try:
            return get_unit_system()
        except Exception:
            pass
    return getattr(api, "unit_system", None)


def _weather_units(api):
    """Return the units Garmin uses for weather values for this account."""
    system = str(_get_user_unit_system(api) or "metric").lower()
    if system == "statute_us":
        return "°F", "mph"
    if system in ("statute_uk", "statute"):
        return "°C", "mph"
    return "°C", "m/s"


def enrich_activity(api, activity):
    """Enrich one activity with detail, GAP, elevation, weather and API splits."""
    if not isinstance(activity, dict) or not activity.get("activityId"):
        return activity

    try:
        detail = api.get_activity(activity["activityId"]) or {}
    except Exception:
        detail = {}

    summary = detail.get("summaryDTO", {}) if isinstance(detail, dict) else {}
    if not isinstance(summary, dict):
        summary = {}

    def pick(keys):
        value = generator.deep_get(summary, keys, None)
        return value if value is not None else generator.deep_get(detail, keys, None)

    # Preserve the activity's actual local start timestamp from Garmin.
    start_local = pick(("startTimeLocal", "startTimeLocalFormatted"))
    if start_local is not None:
        activity["start_time_local"] = start_local

    # Preserve existing output and add only the requested activity-level
    # Training Effect / Exercise Load metrics when Garmin actually returns them.
    aerobic_te = pick(("trainingEffect", "aerobicTrainingEffect"))
    anaerobic_te = pick(("anaerobicTrainingEffect",))
    exercise_load = pick(("exerciseLoad", "trainingLoad", "activityTrainingLoad"))
    if aerobic_te is not None:
        activity["aerobic_te"] = generator.safe_float(aerobic_te, 1)
    if anaerobic_te is not None:
        activity["anaerobic_te"] = generator.safe_float(anaerobic_te, 1)
    if exercise_load is not None:
        activity["exercise_load"] = generator.safe_float(exercise_load, 1)

    gap = pick(("avgGradeAdjustedSpeed", "averageGradeAdjustedSpeed", "avgGradeAdjustedPace", "averageGAP", "avgGAP", "gap"))
    if gap is not None:
        activity["gap"] = _pace_from_speed(gap) if isinstance(gap, (int, float)) else gap

    gain = pick(("elevationGain", "totalElevationGain", "sumElevationGain", "ascent", "elevationAscent"))
    loss = pick(("elevationLoss", "totalElevationLoss", "sumElevationLoss", "descent", "elevationDescent"))
    if gain is not None:
        activity["elevation_gain_m"] = generator.safe_float(gain, 1)
    if loss is not None:
        activity["elevation_loss_m"] = generator.safe_float(loss, 1)

    weather = None
    get_weather = getattr(api, "get_activity_weather", None)
    if callable(get_weather):
        try:
            raw_weather = get_weather(activity["activityId"])
            weather = raw_weather[0] if isinstance(raw_weather, list) and raw_weather else raw_weather if isinstance(raw_weather, dict) else None
        except Exception:
            weather = None

    if weather is None:
        weather = detail.get("weatherDTO") or detail.get("weather") or summary.get("weatherDTO") or summary.get("weather")

    if isinstance(weather, dict):
        temperature_unit, wind_speed_unit = _weather_units(api)
        weather_out = {}
        temperature = generator.deep_get(weather, ("temperature", "temperatureC", "avgTemperature", "averageTemperature"), None)
        if temperature is not None:
            weather_out["temperature"] = generator.safe_float(temperature, 1)
            weather_out["temperature_unit"] = temperature_unit

        humidity = generator.deep_get(weather, ("humidity", "relativeHumidity", "humidityPercent"), None)
        if humidity is not None:
            weather_out["humidity_pct"] = generator.safe_float(humidity, 1)

        wind_speed = generator.deep_get(weather, ("windSpeed", "windSpeedMps", "averageWindSpeed"), None)
        if wind_speed is not None:
            weather_out["wind_speed"] = generator.safe_float(wind_speed, 1)
            weather_out["wind_speed_unit"] = wind_speed_unit

        wind_direction = generator.deep_get(weather, ("windDirection", "windDirectionDegrees"), None)
        if wind_direction is not None:
            weather_out["wind_direction_deg"] = generator.safe_float(wind_direction, 0)

        feels_like = generator.deep_get(weather, ("feelsLike", "feelsLikeTemperature", "apparentTemperature"), None)
        if feels_like is not None:
            weather_out["feels_like"] = generator.safe_float(feels_like, 1)
            weather_out["feels_like_unit"] = temperature_unit

        precipitation = generator.deep_get(weather, ("precipitation", "precipitationMm", "rainfall"), None)
        if precipitation is not None:
            weather_out["precipitation"] = generator.safe_float(precipitation, 1)
            weather_out["precipitation_unit"] = "in" if str(_get_user_unit_system(api) or "metric").lower() == "statute_us" else "mm"

        condition = generator.deep_get(weather, ("condition", "weatherCondition", "description", "weatherType"), None)
        if condition is not None:
            weather_out["condition"] = condition
        if weather_out:
            activity["weather"] = weather_out

    enrich_activity_splits(api, activity)
    return activity

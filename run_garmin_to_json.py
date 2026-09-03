"""Entry point for sport-aware Garmin JSON generation."""

from datetime import timedelta

import garmin_to_json as generator
from activity_zones import add_activity_zones


SPORTS = (
    "running",
    "cycling",
    "swimming",
    "multisport",
    "strength",
    "mobility",
    "walking",
    "transition",
    "other",
)
ENDURANCE_SPORTS = {"running", "cycling", "swimming", "multisport"}


def _activity_text(act):
    values = []
    for key in ("activityType.typeKey", "activityType", "sport", "sportType", "type", "name", "activityName"):
        value = generator.deep_get(act, [key], "")
        if value:
            values.append(str(value).lower())
    return " ".join(values)


def _history_sport(act):
    raw = _activity_text(act)
    if any(x in raw for x in ("strength", "weight_training", "weighttraining", "cardio_strength", "gym", "functional_strength")):
        return "strength"
    if any(x in raw for x in ("mobility", "stretch", "flexibility", "yoga", "pilates")):
        return "mobility"
    if "walk" in raw or "walking" in raw or "hike" in raw or "hiking" in raw:
        return "walking"
    if "transition" in raw:
        return "transition"
    if "run" in raw or "jog" in raw:
        return "running"
    if any(x in raw for x in ("cycl", "bike", "biking")):
        return "cycling"
    if "swim" in raw:
        return "swimming"
    if any(x in raw for x in ("multi", "triathlon", "duathlon", "aquathlon")):
        return "multisport"
    return "other"


def _history_empty():
    return {"activity_count": 0, "distance_km": 0.0, "duration_hours": 0.0, "exercise_load": 0.0, "exercise_load_available": False}


def _history_add(bucket, act):
    bucket["activity_count"] += 1
    bucket["distance_km"] += generator._history_distance_km(act)
    bucket["duration_hours"] += generator._history_duration_hours(act)
    load = generator._history_load(act)
    if load is not None:
        bucket["exercise_load"] += load
        bucket["exercise_load_available"] = True


def _history_finalize(bucket):
    out = {"activity_count": bucket["activity_count"], "distance_km": round(bucket["distance_km"], 2), "duration_hours": round(bucket["duration_hours"], 2)}
    if bucket.get("exercise_load_available"):
        out["exercise_load"] = round(bucket["exercise_load"], 1)
    return out


def _merge(buckets):
    total = _history_empty()
    for bucket in buckets:
        total["activity_count"] += bucket["activity_count"]
        total["distance_km"] += bucket["distance_km"]
        total["duration_hours"] += bucket["duration_hours"]
        if bucket.get("exercise_load_available"):
            total["exercise_load"] += bucket["exercise_load"]
            total["exercise_load_available"] = True
    return total


def get_training_history(api, target_date):
    start_history_date = target_date - timedelta(days=27)
    try:
        historical_activities = api.get_activities_by_date(start_history_date.isoformat(), target_date.isoformat())
    except Exception:
        historical_activities = []
    historical_activities = generator._history_expand_multisport(api, historical_activities)
    by_date = {}
    for act in historical_activities:
        d = generator._history_date(act, target_date)
        by_date.setdefault(d, []).append(act)

    def window(start_date, end_date):
        buckets = {s: _history_empty() for s in SPORTS}
        for d, acts in by_date.items():
            if start_date <= d <= end_date:
                for act in acts:
                    _history_add(buckets[_history_sport(act)], act)
        endurance = _merge([buckets[s] for s in ENDURANCE_SPORTS])
        total_training = _merge(list(buckets.values()))
        return buckets, endurance, total_training

    seven_start = target_date - timedelta(days=6)
    seven_sport, seven_endurance, seven_training = window(seven_start, target_date)
    weekly = []
    for i in range(4):
        week_end = target_date - timedelta(days=i * 7)
        week_start = week_end - timedelta(days=6)
        buckets, endurance, total_training = window(week_start, week_end)
        weekly.append({
            "week_start": week_start.isoformat(), "week_end": week_end.isoformat(),
            "total_endurance": _history_finalize(endurance),
            "total_training": _history_finalize(total_training),
            "sports": {s: _history_finalize(buckets[s]) for s in SPORTS if buckets[s]["activity_count"] > 0},
        })
    weekly.reverse()
    sport_7 = {s: _history_finalize(seven_sport[s]) for s in SPORTS if seven_sport[s]["activity_count"] > 0}
    total_7_endurance = _history_finalize(seven_endurance)
    total_7_training = _history_finalize(seven_training)
    running_weekly = [w["sports"].get("running", {}).get("distance_km", 0.0) for w in weekly]
    running_28_total = round(sum(running_weekly), 2)
    running_avg = round(running_28_total / len(running_weekly), 1) if running_weekly else 0.0
    running_7 = sport_7.get("running", {}).get("distance_km", 0.0)
    return {
        "7_day": {"total_endurance": total_7_endurance, "total_training": total_7_training, "sports": sport_7},
        "28_day": {"avg_weekly_running_distance_km": running_avg, "total_running_distance_km": running_28_total, "weekly_total_endurance": weekly},
        "running_volume": {"7_day_km": running_7, "28_day_km": running_28_total, "28_day_avg_weekly_km": running_avg},
        "legacy_running_summary": {"7_day_distance_km": running_7, "28_day_avg_weekly_distance_km": running_avg, "weekly_distance_last_4_weeks_km": running_weekly},
    }


def _first(source, keys):
    return generator.deep_get(source, keys, None)


def _enrich_activity_environment(api, activity):
    """Add activity-level GAP, elevation and Garmin weather when available."""
    if not isinstance(activity, dict):
        return activity
    aid = activity.get("activityId")
    if not aid:
        return activity
    try:
        detail = api.get_activity(aid) or {}
    except Exception:
        detail = {}
    summary = detail.get("summaryDTO", {}) if isinstance(detail, dict) else {}
    if not isinstance(summary, dict):
        summary = {}

    def pick(keys):
        return _first(summary, keys) if _first(summary, keys) is not None else _first(detail, keys)

    # GAP field names vary across Garmin endpoints/firmware versions.
    gap = pick(("averageGradeAdjustedPace", "avgGradeAdjustedPace", "gradeAdjustedPace", "averageGAP", "avgGAP", "gap"))
    if gap is not None:
        try:
            # Garmin may expose GAP as seconds/km or as a pace string.
            if isinstance(gap, (int, float)):
                gap = generator.format_pace(1000, float(gap), "run") if float(gap) < 100 else None
            activity["gap"] = gap
        except Exception:
            activity["gap"] = gap

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
            raw_weather = get_weather(aid)
            if isinstance(raw_weather, list):
                weather = raw_weather[0] if raw_weather else None
            elif isinstance(raw_weather, dict):
                weather = raw_weather
        except Exception:
            weather = None
    if weather is None:
        weather = detail.get("weatherDTO") or detail.get("weather") or summary.get("weatherDTO") or summary.get("weather")
    if isinstance(weather, dict):
        weather_out = {}
        for out_key, keys, decimals in (
            ("temperature_c", ("temperature", "temperatureC", "avgTemperature", "averageTemperature"), 1),
            ("humidity_pct", ("humidity", "relativeHumidity", "humidityPercent"), 1),
            ("wind_speed_mps", ("windSpeed", "windSpeedMps", "averageWindSpeed"), 1),
            ("wind_direction_deg", ("windDirection", "windDirectionDegrees"), 0),
            ("feels_like_c", ("feelsLike", "feelsLikeTemperature", "apparentTemperature"), 1),
            ("precipitation_mm", ("precipitation", "precipitationMm", "rainfall"), 1),
        ):
            value = _first(weather, keys)
            if value is not None:
                weather_out[out_key] = generator.safe_float(value, decimals)
        condition = _first(weather, ("condition", "weatherCondition", "description", "weatherType"))
        if condition is not None:
            weather_out["condition"] = condition
        if weather_out:
            activity["weather"] = weather_out
    return activity


def get_activities(api, target_date):
    date_str = target_date.isoformat() if hasattr(target_date, "isoformat") else str(target_date)
    activities = _original_get_activities(api, date_str)
    enriched = [_enrich_activity_environment(api, dict(a)) for a in activities or []]
    return add_activity_zones(api, enriched)


_original_get_activities = generator.get_activities
generator.get_activities = get_activities
generator.get_training_history = get_training_history


if __name__ == "__main__":
    generator.main()

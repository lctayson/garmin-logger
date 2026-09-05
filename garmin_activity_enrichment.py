from collections import OrderedDict
from datetime import timedelta

import garmin_to_json as generator
from activity_zones import add_activity_zones


SPLIT_COLUMN_ORDER = (
    "interval", "step_type", "lap", "time", "distance_km", "avg_pace", "avg_gap",
    "avg_hr", "max_hr", "elevation_gain_m", "elevation_loss_m", "avg_run_cadence",
    "avg_ground_contact_time_ms", "avg_stride_length_m", "avg_vertical_oscillation_cm",
    "avg_vertical_ratio_pct", "normalized_power_w", "avg_power_w", "avg_w_kg", "max_power_w",
    "calories", "best_pace", "max_run_cadence", "moving_time", "avg_moving_pace",
)

DUPLICATE_SPLIT_FIELDS = (
    "time_min", "moving_time_min", "cadence_spm", "max_cadence_spm", "ground_contact_ms",
    "vertical_oscillation_cm", "vertical_ratio_pct", "avg_gct_ms", "avg_stride_length_m",
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
    ordered = OrderedDict()
    for key in SPLIT_COLUMN_ORDER:
        if key in item and item[key] is not None:
            ordered[key] = item[key]
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
    by_lap = {x.get("lap"): x for x in existing if isinstance(x, dict) and x.get("lap") is not None}
    fields = (
        ("elevationGain", "elevation_gain_m", 1), ("elevationLoss", "elevation_loss_m", 1),
        ("averageHR", "avg_hr", 0), ("maxHR", "max_hr", 0), ("averageRunCadence", "avg_run_cadence", 0),
        ("groundContactTime", "avg_ground_contact_time_ms", 1), ("verticalOscillation", "avg_vertical_oscillation_cm", 1),
        ("verticalRatio", "avg_vertical_ratio_pct", 1), ("normalizedPower", "normalized_power_w", 0),
        ("averagePower", "avg_power_w", 0), ("maxPower", "max_power_w", 0), ("calories", "calories", 0),
    )
    for lap in laps:
        if not isinstance(lap, dict):
            continue
        lap_number = lap.get("lapIndex")
        item = by_lap.get(lap_number)
        if item is None:
            continue
        for key in DUPLICATE_SPLIT_FIELDS:
            item.pop(key, None)
        if lap.get("intensityType") is not None:
            item["step_type"] = lap["intensityType"]
        for key in ("intensity", "cumulative_time", "cumulative_time_min", "intensityType"):
            item.pop(key, None)
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
    get_unit_system = getattr(api, "get_unit_system", None)
    if callable(get_unit_system):
        try:
            return get_unit_system()
        except Exception:
            pass
    return getattr(api, "unit_system", None)


def _weather_units(api):
    system = str(_get_user_unit_system(api) or "metric").lower()
    if system == "statute_us":
        return "°F", "mph"
    if system in ("statute_uk", "statute"):
        return "°C", "mph"
    return "°C", "m/s"


def _unwrap_weather_value(value):
    if isinstance(value, dict):
        for key in ("value", "numericValue", "number", "amount"):
            if value.get(key) is not None:
                return value[key]
    return value


def _find_weather_value(source, aliases):
    """Find a weather field anywhere in Garmin's nested weather response."""
    aliases = {str(alias).lower() for alias in aliases}
    if isinstance(source, dict):
        for key, value in source.items():
            if str(key).lower() in aliases:
                value = _unwrap_weather_value(value)
                if value is not None and value != "":
                    return value
        for value in source.values():
            found = _find_weather_value(value, aliases)
            if found is not None:
                return found
    elif isinstance(source, list):
        for value in source:
            found = _find_weather_value(value, aliases)
            if found is not None:
                return found
    return None


def _find_weather_field(source, aliases):
    """Return (matched_key, value) so explicit C/F fields can be normalized safely."""
    aliases = {str(alias).lower() for alias in aliases}
    if isinstance(source, dict):
        for key, value in source.items():
            if str(key).lower() in aliases:
                value = _unwrap_weather_value(value)
                if value is not None and value != "":
                    return str(key).lower(), value
        for value in source.values():
            found = _find_weather_field(value, aliases)
            if found is not None:
                return found
    elif isinstance(source, list):
        for value in source:
            found = _find_weather_field(value, aliases)
            if found is not None:
                return found
    return None


def _weather_observation(raw_weather):
    """Normalize Garmin weather endpoint variants to one observation dict."""
    if isinstance(raw_weather, list):
        candidates = raw_weather
    elif isinstance(raw_weather, dict):
        candidates = []
        for key in ("weather", "weatherDTO", "weatherObservation", "weatherObservations", "observations", "data"):
            value = raw_weather.get(key)
            if isinstance(value, list):
                candidates.extend(value)
            elif isinstance(value, dict):
                candidates.append(value)
        candidates.append(raw_weather)
    else:
        return None
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if any(_find_weather_value(candidate, aliases) is not None for aliases in (("temperature", "temp", "airTemperature", "currentTemperature", "temperatureC", "temperatureF"), ("humidity", "relativeHumidity", "humidityPercent"), ("windSpeed", "windSpeedMps", "averageWindSpeed"))):
            return candidate
    return candidates[0] if candidates and isinstance(candidates[0], dict) else None


def _normalize_temperature(value, source_key, account_unit):
    """Normalize Garmin weather temperature to the account-preferred unit.

    Garmin's weather endpoint can return explicit temperatureC/temperatureF
    fields, but generic temp/temperature values have no reliable unit marker.
    For generic fields we therefore trust Garmin's account measurement system;
    we only convert when the payload itself explicitly identifies C or F.
    """
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    key = str(source_key or "").lower()
    if key in {"temperaturef", "tempf", "fahrenheit"} and account_unit == "°C":
        value = (value - 32.0) * 5.0 / 9.0
    elif key in {"temperaturec", "tempc", "celsius"} and account_unit == "°F":
        value = value * 9.0 / 5.0 + 32.0
    return round(value, 1)


def enrich_activity(api, activity):
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

    start_local = pick(("startTimeLocal", "startTimeLocalFormatted"))
    if start_local is not None:
        activity["start_time_local"] = start_local

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

    raw_weather = None
    get_weather = getattr(api, "get_activity_weather", None)
    if callable(get_weather):
        try:
            raw_weather = get_weather(activity["activityId"])
        except Exception:
            raw_weather = None
    weather = _weather_observation(raw_weather)
    if weather is None and isinstance(detail, dict):
        weather = _weather_observation(detail.get("weatherDTO") or detail.get("weather"))
    if isinstance(weather, dict):
        temperature_unit, wind_speed_unit = _weather_units(api)
        weather_out = {}
        temperature_field = _find_weather_field(weather, ("temperature", "temp", "airTemperature", "currentTemperature", "temperatureC", "temperatureF", "tempC", "tempF"))
        if temperature_field is not None:
            source_key, raw_temperature = temperature_field
            temperature = _normalize_temperature(raw_temperature, source_key, temperature_unit)
            if temperature is not None:
                weather_out["temperature"] = temperature
                weather_out["temperature_unit"] = temperature_unit
        humidity = _find_weather_value(weather, ("humidity", "relativeHumidity", "humidityPercent"))
        if humidity is not None:
            weather_out["humidity_pct"] = generator.safe_float(humidity, 1)
        wind_speed = _find_weather_value(weather, ("windSpeed", "windSpeedMps", "averageWindSpeed"))
        if wind_speed is not None:
            weather_out["wind_speed"] = generator.safe_float(wind_speed, 1)
            weather_out["wind_speed_unit"] = wind_speed_unit
        wind_direction = _find_weather_value(weather, ("windDirection", "windDirectionDegrees", "windDirectionDeg"))
        if wind_direction is not None:
            weather_out["wind_direction_deg"] = generator.safe_float(wind_direction, 0)
        feels_like_field = _find_weather_field(weather, ("feelsLike", "feelsLikeTemperature", "apparentTemperature"))
        if feels_like_field is not None:
            _, raw_feels_like = feels_like_field
            feels_like = _normalize_temperature(raw_feels_like, feels_like_field[0], temperature_unit)
            if feels_like is not None:
                weather_out["feels_like"] = feels_like
                weather_out["feels_like_unit"] = temperature_unit
        precipitation = _find_weather_value(weather, ("precipitation", "precipitationMm", "rainfall"))
        if precipitation is not None:
            weather_out["precipitation"] = generator.safe_float(precipitation, 1)
            weather_out["precipitation_unit"] = "in" if str(_get_user_unit_system(api) or "metric").lower() == "statute_us" else "mm"
        condition = _find_weather_value(weather, ("condition", "weatherCondition", "description", "weatherType"))
        if condition is not None:
            weather_out["condition"] = condition
        if weather_out:
            activity["weather"] = weather_out

    enrich_activity_splits(api, activity)
    return activity

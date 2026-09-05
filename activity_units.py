"""Convert user-facing activity JSON to Garmin account-preferred units.

Internal calculations remain metric; this module only changes the exported
activity representation after enrichment/analysis has finished.
"""

M_TO_KM = 1.0 / 1000.0
M_TO_MI = 1.0 / 1609.344
M_TO_FT = 3.280839895013123
CM_TO_IN = 0.3937007874015748
M_TO_FT = 3.280839895013123


def _unit_system(api):
    getter = getattr(api, "get_unit_system", None)
    if callable(getter):
        try:
            value = getter()
            if value:
                return str(value).lower()
        except Exception:
            pass
    return str(getattr(api, "unit_system", None) or "metric").lower()


def _is_imperial(system):
    return system in ("statute_us", "statute_uk", "statute")


def _pace_convert(value, to_miles=False):
    """Convert a pace string between min/km and min/mi."""
    if value is None or not isinstance(value, str) or ":" not in value:
        return value
    try:
        minutes, seconds = value.strip().split(":", 1)
        sec_per_km = float(minutes) * 60.0 + float(seconds)
    except (TypeError, ValueError):
        return value
    sec = sec_per_km * 1.609344 if to_miles else sec_per_km / 1.609344
    total = int(round(sec))
    return f"{total // 60}:{total % 60:02d}"


def _pace_from_distance_duration(distance_km, duration_min, to_miles=False):
    try:
        distance_km = float(distance_km)
        duration_min = float(duration_min)
    except (TypeError, ValueError):
        return None
    if distance_km <= 0 or duration_min <= 0:
        return None
    sec_per_km = duration_min * 60.0 / distance_km
    return _pace_convert(f"{int(sec_per_km // 60)}:{int(round(sec_per_km % 60)):02d}", to_miles)


def _convert_split(split, imperial):
    if not isinstance(split, dict):
        return split
    out = dict(split)

    if "distance_km" in out:
        try:
            out["distance"] = round(float(out.pop("distance_km")) * (1.0 if not imperial else 0.621371192237334), 3)
        except (TypeError, ValueError):
            out.pop("distance_km", None)

    for key in ("avg_pace", "avg_gap", "best_pace", "avg_moving_pace"):
        if key in out and imperial:
            out[key] = _pace_convert(out[key], to_miles=True)

    for old, new in (("elevation_gain_m", "elevation_gain"), ("elevation_loss_m", "elevation_loss")):
        if old in out:
            try:
                value = float(out.pop(old))
                out[new] = round(value * (M_TO_FT if imperial else 1.0), 1)
            except (TypeError, ValueError):
                out.pop(old, None)

    if "avg_stride_length_m" in out:
        try:
            value = float(out.pop("avg_stride_length_m"))
            out["stride_length"] = round(value * (M_TO_FT if imperial else 1.0), 2)
        except (TypeError, ValueError):
            out.pop("avg_stride_length_m", None)

    if "avg_vertical_oscillation_cm" in out:
        try:
            value = float(out.pop("avg_vertical_oscillation_cm"))
            out["avg_vertical_oscillation"] = round(value * (CM_TO_IN if imperial else 1.0), 2)
        except (TypeError, ValueError):
            out.pop("avg_vertical_oscillation_cm", None)

    # Unit-neutral names for universally fixed units as well.
    for old, new in (("avg_ground_contact_time_ms", "avg_ground_contact_time"),
                     ("normalized_power_w", "normalized_power"),
                     ("avg_power_w", "avg_power"),
                     ("max_power_w", "max_power"),
                     ("avg_w_kg", "avg_power_w_kg"),
                     ("max_w_kg", "max_power_w_kg")):
        if old in out:
            out[new] = out.pop(old)

    return out


def _convert_activity(activity, api):
    if not isinstance(activity, dict):
        return activity
    imperial = _is_imperial(_unit_system(api))
    distance_unit = "mi" if imperial else "km"
    pace_unit = "min/mi" if imperial else "min/km"
    elevation_unit = "ft" if imperial else "m"
    stride_unit = "ft" if imperial else "m"
    vertical_unit = "in" if imperial else "cm"

    out = dict(activity)
    out["units"] = {
        "distance": distance_unit,
        "pace": pace_unit,
        "elevation": elevation_unit,
        "stride_length": stride_unit,
        "vertical_oscillation": vertical_unit,
    }

    if "distance_km" in out:
        try:
            out["distance"] = round(float(out.pop("distance_km")) * (0.621371192237334 if imperial else 1.0), 2)
        except (TypeError, ValueError):
            out.pop("distance_km", None)

    # Recalculate activity pace from the already-canonical metric distance/time,
    # avoiding a second conversion of an already formatted string.
    if "distance" in out and "duration_mins" in out:
        pace = _pace_from_distance_duration(
            float(out["distance"]) / (0.621371192237334 if imperial else 1.0),
            out["duration_mins"],
            to_miles=imperial,
        )
        if pace is not None:
            out["avg_pace"] = pace

    if "gap" in out and imperial:
        out["gap"] = _pace_convert(out["gap"], to_miles=True)

    for old, new in (("elevation_gain_m", "elevation_gain"), ("elevation_loss_m", "elevation_loss")):
        if old in out:
            try:
                value = float(out.pop(old))
                out[new] = round(value * (M_TO_FT if imperial else 1.0), 1)
            except (TypeError, ValueError):
                out.pop(old, None)

    weather = out.get("weather")
    if isinstance(weather, dict):
        weather = dict(weather)
        for key in ("temperature_unit", "wind_speed_unit", "feels_like_unit", "precipitation_unit"):
            weather.pop(key, None)
        out["weather"] = weather
        out["units"]["temperature"] = "°F" if imperial and _unit_system(api) == "statute_us" else "°C"
        out["units"]["wind_speed"] = "mph" if imperial else "m/s"
        out["units"]["precipitation"] = "in" if _unit_system(api) == "statute_us" else "mm"

    if isinstance(out.get("activity_splits"), list):
        out["activity_splits"] = [_convert_split(s, imperial) for s in out["activity_splits"]]

    return out


def apply_user_units(api, activities):
    """Apply Garmin account measurement preferences to exported activities."""
    return [_convert_activity(activity, api) for activity in (activities or [])]

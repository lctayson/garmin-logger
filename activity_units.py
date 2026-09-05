"""Convert user-facing activity JSON to Garmin account-preferred units.

Internal calculations remain metric; this module only changes the exported
activity representation after enrichment/analysis has finished.
"""

M_TO_FT = 3.280839895013123
CM_TO_IN = 0.3937007874015748
KM_TO_MI = 0.621371192237334


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


def _convert_split(split, imperial):
    if not isinstance(split, dict):
        return split
    out = dict(split)

    if "distance_km" in out:
        try:
            out["distance"] = round(float(out.pop("distance_km")) * (KM_TO_MI if imperial else 1.0), 3)
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

    for old in ("avg_stride_length_m", "stride_length_m"):
        if old in out:
            try:
                value = float(out.pop(old))
                out["stride_length"] = round(value * (M_TO_FT if imperial else 1.0), 2)
            except (TypeError, ValueError):
                out.pop(old, None)

    if "avg_vertical_oscillation_cm" in out:
        try:
            value = float(out.pop("avg_vertical_oscillation_cm"))
            out["avg_vertical_oscillation"] = round(value * (CM_TO_IN if imperial else 1.0), 2)
        except (TypeError, ValueError):
            out.pop("avg_vertical_oscillation_cm", None)

    for old, new in (
        ("avg_ground_contact_time_ms", "avg_ground_contact_time"),
        ("normalized_power_w", "normalized_power"),
        ("avg_power_w", "avg_power"),
        ("max_power_w", "max_power"),
        ("avg_w_kg", "avg_power_to_weight"),
        ("max_w_kg", "max_power_to_weight"),
        ("avg_vertical_ratio_pct", "avg_vertical_ratio"),
    ):
        if old in out:
            out[new] = out.pop(old)

    return out


def _reorder_activity(out):
    """Put activity fields in Garmin Connect-style analysis priority order."""
    priority = (
        # Identity / title
        "activity_id", "name", "type",
        # Primary summary: keep the headline Garmin Connect metrics together.
        "distance", "duration_min", "avg_hr", "avg_pace", "elevation_gain", "elevation_loss", "calories",
        # Core performance metrics
        "max_hr", "gap", "avg_power", "normalized_power", "max_power",
        "avg_run_cadence", "max_run_cadence", "avg_ground_contact_time", "stride_length",
        "avg_vertical_oscillation", "avg_vertical_ratio", "avg_power_to_weight", "max_power_to_weight",
        # Training / recovery metrics
        "aerobic_te", "anaerobic_te", "load", "exercise_load", "recovery_time_hours",
        # Detailed activity data should come before environmental/context metadata.
        "activity_splits", "splits",
        # Context / environment
        "start_time_local", "weather",
        # Zone breakdowns
        "hr_zones", "power_zones",
        # Metadata / conversion information
        "parent_activity_id", "units",
    )
    ordered = {}
    for key in priority:
        if key in out and out[key] is not None:
            ordered[key] = out[key]
    for key, value in out.items():
        if key not in ordered and value is not None:
            ordered[key] = value
    return ordered


def _convert_activity(activity, api):
    if not isinstance(activity, dict):
        return activity
    system = _unit_system(api)
    imperial = _is_imperial(system)
    distance_unit = "mi" if imperial else "km"
    pace_unit = "min/mi" if imperial else "min/km"
    elevation_unit = "ft" if imperial else "m"
    stride_unit = "ft" if imperial else "m"
    vertical_unit = "in" if imperial else "cm"

    out = dict(activity)

    if "distance_km" in out:
        try:
            out["distance"] = round(float(out.pop("distance_km")) * (KM_TO_MI if imperial else 1.0), 2)
        except (TypeError, ValueError):
            out.pop("distance_km", None)

    # Preserve the canonical activity pace produced by the generator/enrichment.
    # Do not recalculate it from duration_mins: Garmin payloads can expose
    # duration fields with different semantics, which previously caused a pace regression.
    if "avg_pace" in out and imperial:
        out["avg_pace"] = _pace_convert(out["avg_pace"], to_miles=True)

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
        # Garmin's generic activity-weather temperature field is returned as
        # Fahrenheit in the payload we receive, even for a metric account.
        # Normalize it here before exposing the account-preferred Celsius unit.
        if not imperial and weather.get("temperature") is not None:
            try:
                weather["temperature"] = round((float(weather["temperature"]) - 32.0) * 5.0 / 9.0, 1)
            except (TypeError, ValueError):
                pass
        for key in ("temperature_unit", "wind_speed_unit", "feels_like_unit", "precipitation_unit"):
            weather.pop(key, None)
        out["weather"] = weather
        out["units"] = {
            "distance": distance_unit,
            "pace": pace_unit,
            "elevation": elevation_unit,
            "stride_length": stride_unit,
            "vertical_oscillation": vertical_unit,
            "temperature": "°F" if imperial and system == "statute_us" else "°C",
            "wind_speed": "mph" if imperial else "m/s",
            "precipitation": "in" if system == "statute_us" else "mm",
        }
    else:
        out["units"] = {
            "distance": distance_unit,
            "pace": pace_unit,
            "elevation": elevation_unit,
            "stride_length": stride_unit,
            "vertical_oscillation": vertical_unit,
        }

    if isinstance(out.get("activity_splits"), list):
        out["activity_splits"] = [_convert_split(s, imperial) for s in out["activity_splits"]]

    return _reorder_activity(out)


def apply_user_units(api, activities):
    """Apply Garmin account measurement preferences and stable field ordering."""
    return [_convert_activity(activity, api) for activity in (activities or [])]

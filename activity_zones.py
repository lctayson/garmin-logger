"""Compact Garmin activity heart-rate and power zone summaries."""


def _seconds(value):
    try:
        value = float(value)
        return max(0.0, value)
    except (TypeError, ValueError):
        return None


def _time_text(seconds):
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _first_value(obj, keys):
    return next((obj.get(key) for key in keys if obj.get(key) is not None), None)


def _zone_metadata(obj):
    """Extract Garmin-supplied zone metadata when available."""
    low = _first_value(obj, (
        "zoneLowBoundary", "zoneLowerBoundary", "lowBoundary", "lowerBoundary",
        "zoneLow", "low",
    ))
    high = _first_value(obj, (
        "zoneHighBoundary", "zoneUpperBoundary", "highBoundary", "upperBoundary",
        "zoneHigh", "high",
    ))
    description = _first_value(obj, (
        "zoneDescription", "zoneName", "description", "name", "displayName",
    ))
    percent = _first_value(obj, (
        "zonePercentage", "percentage", "percent", "percentInZone",
    ))

    try:
        low = int(round(float(low)))
    except (TypeError, ValueError):
        low = None
    try:
        high = int(round(float(high)))
    except (TypeError, ValueError):
        high = None
    try:
        percent = round(float(percent))
    except (TypeError, ValueError):
        percent = None

    return low, high, str(description).strip() if description else None, percent


def _format_zone_range(low, high, metric, zone):
    unit = "bpm" if metric == "hr" else "W"
    if low is not None and high is not None:
        return f"{low}-{high} {unit}"
    if low is not None and zone == 5:
        return f">{low - 1} {unit}"
    return None


def _find_zone_rows(payload, metric):
    rows = []

    def walk(obj):
        if isinstance(obj, dict):
            zone = obj.get("zoneNumber", obj.get("zone"))
            seconds = obj.get("secsInZone", obj.get("secondsInZone"))
            if seconds is None:
                seconds = obj.get("timeInZone", obj.get("duration"))
            try:
                zone_num = int(zone)
            except (TypeError, ValueError):
                zone_num = None
            seconds = _seconds(seconds)
            if zone_num is not None and 1 <= zone_num <= 5 and seconds is not None:
                low, high, description, percent = _zone_metadata(obj)
                rows.append((zone_num, seconds, low, high, description, percent))
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(payload)
    # Garmin payloads can contain the same zone list in more than one wrapper.
    # Keep the last occurrence for each zone, preserving the API's values.
    by_zone = {}
    for zone, seconds, low, high, description, percent in rows:
        by_zone[zone] = (seconds, low, high, description, percent)

    # The activity zone endpoint normally returns zoneLowBoundary but not an
    # explicit upper boundary. Derive each zone's upper bound from the next
    # zone's lower boundary, which preserves the user's Garmin-configured zones.
    for zone in sorted(by_zone):
        seconds, low, high, description, percent = by_zone[zone]
        if high is None:
            next_low = by_zone.get(zone + 1, (None, None, None, None, None))[1]
            if next_low is not None:
                high = next_low - 1
        zone_range = _format_zone_range(low, high, metric, zone)
        by_zone[zone] = (seconds, zone_range, description, percent)

    return [(zone, *by_zone[zone]) for zone in sorted(by_zone)]


def compact_zones(payload, metric="hr"):
    """Return zone data as columns/data, matching the activity split style."""
    rows = _find_zone_rows(payload, metric)
    if not rows:
        return None

    by_zone = {zone: (seconds, zone_range, description, percent) for zone, seconds, zone_range, description, percent in rows}
    total = sum(seconds for seconds, _, _, _ in by_zone.values())
    if total <= 0:
        return None

    data = []
    for zone in range(1, 6):
        seconds, zone_range, description, percent = by_zone.get(zone, (0, None, None, None))
        label = f"Zone {zone}"
        if description:
            label += f" - {description}"
        data.append([
            label,
            zone_range,
            _time_text(seconds),
            percent if percent is not None else round(seconds / total * 100),
        ])

    return {
        "columns": ["zone", "range", "time", "percent"],
        "data": data,
    }


def add_activity_zones(api, activities):
    """Add HR/power zone tables without changing existing activity fields."""
    for activity in activities or []:
        activity_id = activity.get("activityId")
        if not activity_id:
            continue

        try:
            hr_payload = api.get_activity_hr_in_timezones(activity_id)
            hr_zones = compact_zones(hr_payload, "hr")
            if hr_zones:
                activity["hr_zones"] = hr_zones
        except Exception:
            pass

        try:
            power_payload = api.get_activity_power_in_timezones(activity_id)
            power_zones = compact_zones(power_payload, "power")
            if power_zones:
                activity["power_zones"] = power_zones
        except Exception:
            pass

    return activities

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


def _find_zone_rows(payload):
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
                rows.append((zone_num, seconds))
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(payload)
    # Garmin payloads can contain the same zone list in more than one wrapper.
    # Keep the last occurrence for each zone, preserving the API's values.
    by_zone = {}
    for zone, seconds in rows:
        by_zone[zone] = seconds
    return [(zone, by_zone[zone]) for zone in sorted(by_zone)]


def compact_zones(payload):
    """Return [[time_text, percent], ...] in fixed Z1..Z5 order."""
    rows = _find_zone_rows(payload)
    if not rows:
        return None
    by_zone = dict(rows)
    total = sum(by_zone.values())
    if total <= 0:
        return None
    return [
        [_time_text(by_zone.get(zone, 0)), round(by_zone.get(zone, 0) / total * 100)]
        for zone in range(1, 6)
    ]


def add_activity_zones(api, activities):
    """Add compact HR/power zone summaries without changing existing activity fields."""
    for activity in activities or []:
        activity_id = activity.get("activityId")
        if not activity_id:
            continue

        try:
            hr_payload = api.get_activity_hr_in_timezones(activity_id)
            hr_zones = compact_zones(hr_payload)
            if hr_zones:
                activity["hr_zones"] = hr_zones
        except Exception:
            pass

        # Power zones are relevant when Garmin has power data. Do not fail the
        # activity export when this endpoint is unavailable for a sport/device.
        try:
            power_payload = api.get_activity_power_in_timezones(activity_id)
            power_zones = compact_zones(power_payload)
            if power_zones:
                activity["power_zones"] = power_zones
        except Exception:
            pass

    return activities

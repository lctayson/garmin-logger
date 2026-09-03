"""Compact Garmin activity heart-rate and power zone summaries."""


# Current zone boundaries used by the runner's Garmin profile.  Garmin's
# time-in-zone endpoints provide duration but do not consistently include the
# display range, so these are used when the endpoint payload has no boundary.
HR_ZONE_RANGES = {
    1: "110-145 bpm",
    2: "146-152 bpm",
    3: "153-163 bpm",
    4: "164-169 bpm",
    5: ">169 bpm",
}
POWER_ZONE_RANGES = {
    1: "196-240 W",
    2: "241-271 W",
    3: "272-300 W",
    4: "301-346 W",
    5: ">346 W",
}


def _seconds(value):
    try:
        value = float(value)
        return max(0.0, value)
    except (TypeError, ValueError):
        return None


def _time_text(seconds):
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _zone_range(obj, metric, zone):
    """Read a zone boundary from Garmin when available, otherwise use defaults."""
    low_keys = (
        "zoneLowBoundary",
        "zoneLowerBoundary",
        "lowBoundary",
        "lowerBoundary",
        "zoneLow",
        "low",
    )
    high_keys = (
        "zoneHighBoundary",
        "zoneUpperBoundary",
        "highBoundary",
        "upperBoundary",
        "zoneHigh",
        "high",
    )

    low = next((obj.get(key) for key in low_keys if obj.get(key) is not None), None)
    high = next((obj.get(key) for key in high_keys if obj.get(key) is not None), None)

    try:
        low = int(round(float(low)))
    except (TypeError, ValueError):
        low = None
    try:
        high = int(round(float(high)))
    except (TypeError, ValueError):
        high = None

    if low is not None and high is not None:
        unit = "bpm" if metric == "hr" else "W"
        return f"{low}-{high} {unit}"
    if low is not None and zone == 5:
        unit = "bpm" if metric == "hr" else "W"
        return f">{low - 1} {unit}"

    defaults = HR_ZONE_RANGES if metric == "hr" else POWER_ZONE_RANGES
    return defaults[zone]


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
                rows.append((zone_num, seconds, _zone_range(obj, metric, zone_num)))
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(payload)
    # Garmin payloads can contain the same zone list in more than one wrapper.
    # Keep the last occurrence for each zone, preserving the API's values.
    by_zone = {}
    for zone, seconds, zone_range in rows:
        by_zone[zone] = (seconds, zone_range)
    return [(zone, *by_zone[zone]) for zone in sorted(by_zone)]


def compact_zones(payload, metric="hr"):
    """Return zone data as columns/data, matching the activity split style."""
    rows = _find_zone_rows(payload, metric)
    if not rows:
        return None

    by_zone = {zone: (seconds, zone_range) for zone, seconds, zone_range in rows}
    total = sum(seconds for seconds, _ in by_zone.values())
    if total <= 0:
        return None

    unit_label = "Warm Up" if metric == "hr" else None
    data = []
    for zone in range(1, 6):
        seconds, zone_range = by_zone.get(zone, (0, (HR_ZONE_RANGES if metric == "hr" else POWER_ZONE_RANGES)[zone]))
        label = f"Zone {zone}"
        if zone == 1 and unit_label:
            label += f" - {unit_label}"
        data.append([
            label,
            zone_range,
            _time_text(seconds),
            round(seconds / total * 100),
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

        # Power zones are relevant when Garmin has power data. Do not fail the
        # activity export when this endpoint is unavailable for a sport/device.
        try:
            power_payload = api.get_activity_power_in_timezones(activity_id)
            power_zones = compact_zones(power_payload, "power")
            if power_zones:
                activity["power_zones"] = power_zones
        except Exception:
            pass

    return activities

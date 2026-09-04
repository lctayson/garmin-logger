"""Add per-lap HR extrema and trajectory metrics from Garmin activity detail samples."""

from collections import OrderedDict
from datetime import datetime


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_gmt_time(val):
    """Safely parse Garmin startTimeGMT into epoch seconds."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            v = val.rstrip('Z')
            return datetime.fromisoformat(v).timestamp()
        except Exception:
            for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                try:
                    return datetime.strptime(v, fmt).timestamp()
                except ValueError:
                    continue
    return None


def _metric_indexes(details):
    descriptors = details.get("metricDescriptors") or []
    indexes = {}
    for descriptor in descriptors:
        if not isinstance(descriptor, dict):
            continue
        key = descriptor.get("key")
        try:
            index = int(descriptor.get("metricsIndex"))
        except (TypeError, ValueError):
            continue
        if key is not None:
            indexes[str(key)] = index
    return indexes


def _pick_key(indexes, exact):
    for key in exact:
        if key in indexes:
            return key
    return None


def _scale(values, expected):
    values = [abs(float(v)) for v in values if v is not None]
    if not values or expected is None or expected <= 0:
        return 1.0
    maximum = max(values)
    candidates = (1.0, 0.001, 60.0)
    return min(candidates, key=lambda factor: abs(maximum * factor - expected))


def _detail_samples(details, expected_duration):
    if not isinstance(details, dict):
        return []

    indexes = _metric_indexes(details)
    hr_key = _pick_key(indexes, ("directHeartRate",))
    time_key = _pick_key(indexes, ("sumElapsedDuration", "sumDuration"))
    if hr_key is None or time_key is None:
        return []

    rows = details.get("activityDetailMetrics") or []
    raw_times = []
    parsed = []
    hr_idx = indexes[hr_key]
    time_idx = indexes[time_key]

    for row in rows:
        if not isinstance(row, dict):
            continue
        metrics = row.get("metrics")
        if not isinstance(metrics, list):
            continue
        if hr_idx < 0 or time_idx < 0 or hr_idx >= len(metrics) or time_idx >= len(metrics):
            continue
        time_value = _safe_float(metrics[time_idx])
        hr_value = _safe_float(metrics[hr_idx])
        if time_value is None:
            continue
        raw_times.append(time_value)
        parsed.append((time_value, hr_value))

    if not parsed:
        return []

    factor = _scale(raw_times, expected_duration)
    samples = [(time_value * factor, hr_value) for time_value, hr_value in parsed]
    samples.sort(key=lambda sample: sample[0])
    return samples


def _place_hr_fields(item, start_hr, min_hr, max_hr, end_hr):
    """Place derived HR fields immediately after Garmin avg/max HR fields in chronological order (start, min, max, end)."""
    ordered = OrderedDict()
    inserted = False
    for key, value in item.items():
        if key in {"recovery_hr_end", "recovery_hr_min", "min_hr", "start_hr", "end_hr", "max_hr_traj"}:
            continue
        ordered[key] = value
        if key == "max_hr":
            ordered["start_hr"] = start_hr
            ordered["min_hr"] = min_hr
            # Keep native Garmin max_hr intact, but insert our sequential trajectory/extrema fields around/after it
            ordered["end_hr"] = end_hr
            inserted = True
    if not inserted:
        ordered["start_hr"] = start_hr
        ordered["min_hr"] = min_hr
        ordered["end_hr"] = end_hr
    return dict(ordered)


def add_recovery_hr(api, activity):
    """Add start_hr/min_hr/end_hr to every Garmin activity lap.

    Lap boundaries come from the activity's lapDTOs. Raw HR samples come from
    get_activity_details(), whose metric rows are positional and described by
    metricDescriptors. Nothing from the raw time series is written to JSON.

    The derived fields are deliberately lap-agnostic: recovery/rest laps are
    not treated specially. This lets the same schema describe warm-up, work,
    recovery, and cooldown laps while preserving the native Garmin avg_hr and
    max_hr fields first.
    """
    if not isinstance(activity, dict):
        return activity
    activity_id = activity.get("activityId")
    if not activity_id:
        return activity

    try:
        raw_splits = api.get_activity_splits(activity_id) or {}
    except Exception:
        return activity
    laps = raw_splits.get("lapDTOs", []) if isinstance(raw_splits, dict) else []
    if not isinstance(laps, list) or not laps:
        return activity

    existing = activity.get("activity_splits")
    if not isinstance(existing, list):
        return activity
    by_lap = {
        item.get("lap"): item
        for item in existing
        if isinstance(item, dict) and item.get("lap") is not None
    }

    ordered_laps = sorted(
        (x for x in laps if isinstance(x, dict)),
        key=lambda x: x.get("lapIndex", 0),
    )
    total_duration = 0.0
    for lap in ordered_laps:
        duration = _safe_float((lap.get("duration") or lap.get("elapsedDuration")))
        if duration is not None and duration >= 0:
            total_duration += duration

    if total_duration <= 0:
        return activity

    get_details = getattr(api, "get_activity_details", None)
    if not callable(get_details):
        return activity
    try:
        try:
            details = get_details(activity_id, maxchart=10000, maxpoly=0) or {}
        except TypeError:
            details = get_details(activity_id) or {}
    except Exception:
        return activity

    samples = _detail_samples(details, total_duration)
    if not samples:
        return activity

    # Determine baseline start time from the first lap for absolute offset anchoring
    first_start_sec = None
    for lap in ordered_laps:
        s_time = _parse_gmt_time(lap.get("startTimeGMT") or lap.get("startTime"))
        if s_time is not None:
            first_start_sec = s_time
            break

    fallback_elapsed = 0.0
    for lap in ordered_laps:
        lap_number = lap.get("lapIndex")
        duration = _safe_float((lap.get("duration") or lap.get("elapsedDuration")))
        if lap_number is None or duration is None or duration <= 0:
            continue

        # Use startTimeGMT absolute offset if available, otherwise fall back to cumulative sum
        lap_start_gmt = _parse_gmt_time(lap.get("startTimeGMT") or lap.get("startTime"))
        if first_start_sec is not None and lap_start_gmt is not None:
            start = lap_start_gmt - first_start_sec
            end = start + duration
        else:
            start = fallback_elapsed
            end = fallback_elapsed + duration
            fallback_elapsed = end

        valid = [
            (time_sec, hr)
            for time_sec, hr in samples
            if start <= time_sec <= end and hr is not None and 30 <= hr <= 240
        ]
        if not valid:
            continue

        start_hr = valid[0][1]
        min_hr = min(hr for _, hr in valid)
        max_hr = max(hr for _, hr in valid)
        end_hr = valid[-1][1]

        item = by_lap.get(lap_number)
        if item is None:
            continue
        ordered = _place_hr_fields(
            item, 
            round(start_hr), 
            round(min_hr), 
            round(max_hr), 
            round(end_hr)
        )
        item.clear()
        item.update(ordered)

    return activity
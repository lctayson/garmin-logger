"""Add recovery-interval HR metrics from Garmin activity detail samples."""


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
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
    return [(time_value * factor, hr_value) for time_value, hr_value in parsed]


def _recovery_type(value):
    if value is None:
        return False
    value = str(value).upper()
    return value in {"RECOVERY", "REST", "RESTING"}


def add_recovery_hr(api, activity):
    """Add recovery_hr_end and recovery_hr_min to Garmin recovery/rest laps.

    Lap boundaries come from the activity's lapDTOs. Raw HR samples come from
    get_activity_details(), whose metric rows are positional and described by
    metricDescriptors. Nothing from the raw time series is written to JSON.
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

    total_duration = 0.0
    for lap in sorted(
        (x for x in laps if isinstance(x, dict)),
        key=lambda x: x.get("lapIndex", 0),
    ):
        duration = _safe_float(lap.get("duration"))
        if duration is None or duration < 0:
            continue
        total_duration += duration

    if total_duration <= 0:
        return activity

    get_details = getattr(api, "get_activity_details", None)
    if not callable(get_details):
        return activity
    try:
        # Use a high chart size because recovery intervals are short and the
        # endpoint otherwise downsamples the whole activity too aggressively.
        try:
            details = get_details(activity_id, maxchart=10000, maxpoly=0) or {}
        except TypeError:
            details = get_details(activity_id) or {}
    except Exception:
        return activity

    samples = _detail_samples(details, total_duration)
    if not samples:
        return activity

    elapsed = 0.0
    for lap in sorted(
        (x for x in laps if isinstance(x, dict)),
        key=lambda x: x.get("lapIndex", 0),
    ):
        lap_number = lap.get("lapIndex")
        duration = _safe_float(lap.get("duration"))
        if lap_number is None or duration is None or duration <= 0:
            continue

        start = elapsed
        end = elapsed + duration
        elapsed = end

        step_type = lap.get("intensityType")
        if not _recovery_type(step_type):
            item = by_lap.get(lap_number)
            step_type = item.get("step_type") if isinstance(item, dict) else None
        if not _recovery_type(step_type):
            continue

        values = [
            hr for time_sec, hr in samples
            if start <= time_sec <= end and hr is not None and 30 <= hr <= 240
        ]
        if not values:
            continue

        # The endpoint can omit the exact boundary sample. Prefer the last
        # valid sample at or before the boundary; allow a small pre-boundary
        # gap but never use a sample from the following repetition.
        end_candidates = [
            (time_sec, hr)
            for time_sec, hr in samples
            if start <= time_sec <= end and hr is not None and 30 <= hr <= 240
        ]
        if end_candidates:
            recovery_end = end_candidates[-1][1]
        else:
            recovery_end = None

        item = by_lap.get(lap_number)
        if item is None:
            continue
        item["recovery_hr_end"] = round(recovery_end) if recovery_end is not None else None
        item["recovery_hr_min"] = round(min(values))

    activity["activity_splits"] = [
        item for item in activity["activity_splits"]
    ]
    return activity

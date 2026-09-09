"""Add a per-activity Performance Condition summary from Garmin's in-run detail stream.

Garmin does not publish a per-activity VO2max (see activity_vo2max), but it does
compute a real-time "Performance Condition" score (-20 to +20) during a run,
comparing effort against your established fitness level. Garmin only exposes
this as a raw per-second time series in get_activity_details(), never as a
summary field, so this module extracts and condenses it.
"""


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


def _performance_condition_samples(details):
    if not isinstance(details, dict):
        return []
    indexes = _metric_indexes(details)
    pc_idx = indexes.get("directPerformanceCondition")
    if pc_idx is None:
        return []
    rows = details.get("activityDetailMetrics") or []
    samples = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        metrics = row.get("metrics")
        if not isinstance(metrics, list) or pc_idx >= len(metrics):
            continue
        value = _safe_float(metrics[pc_idx])
        if value is not None:
            samples.append(value)
    return samples


def add_performance_condition(api, activity):
    """Summarize the directPerformanceCondition stream as start/end/avg fields."""
    if not isinstance(activity, dict) or not activity.get("activityId"):
        return activity
    if str(activity.get("type", "")).lower() != "running":
        return activity

    get_details = getattr(api, "get_activity_details", None)
    if not callable(get_details):
        return activity
    try:
        try:
            details = get_details(activity["activityId"], maxchart=10000, maxpoly=0) or {}
        except TypeError:
            details = get_details(activity["activityId"]) or {}
    except Exception:
        return activity

    samples = _performance_condition_samples(details)
    if not samples:
        return activity

    activity["performance_condition_start"] = round(samples[0])
    activity["performance_condition_end"] = round(samples[-1])
    activity["performance_condition_avg"] = round(sum(samples) / len(samples), 1)
    return activity

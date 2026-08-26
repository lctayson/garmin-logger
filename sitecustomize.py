"""Startup compatibility patches for garmin_to_json.py."""

import builtins
from datetime import datetime

import garmin_helpers as _helpers
from garmin_helpers import (
    get_training_status_details,
    get_metric_trend,
    get_body_battery_trend,
    get_activities as _original_get_activities,
)


def _get_activities_for_export(api, target_date_str):
    """Export activities for exactly one date, with a date-specific retry path.

    The primary path remains the existing date-range endpoint. If that endpoint
    returns no records, use Garmin's dedicated for-date endpoint for the same
    exact date. No adjacent dates and no recent-activities query are used.
    """
    activities = _original_get_activities(api, target_date_str)
    if activities:
        return activities

    try:
        raw = api.get_activities_fordate(target_date_str)
    except Exception as exc:
        print(f"[activities] Warning: date-specific lookup failed for {target_date_str}: {exc}")
        return []

    if isinstance(raw, list):
        date_activities = raw
    elif isinstance(raw, dict):
        date_activities = []
        for key in ("activityList", "activities", "activityData", "activityDTOs", "activityDTO"):
            value = raw.get(key)
            if isinstance(value, list):
                date_activities = value
                break
            if isinstance(value, dict):
                date_activities = [value]
                break
    else:
        date_activities = []

    if not date_activities:
        return []

    # Reuse the normal formatter without changing its date-selection behavior.
    original = api.get_activities_by_date
    try:
        api.get_activities_by_date = lambda start, end, *args, **kwargs: date_activities if start == target_date_str and end == target_date_str else []
        return _original_get_activities(api, target_date_str)
    finally:
        api.get_activities_by_date = original


builtins.get_training_status_details = get_training_status_details
builtins.get_metric_trend = get_metric_trend
builtins.get_body_battery_trend = get_body_battery_trend
builtins.get_activities = _get_activities_for_export

try:
    from garminconnect import Garmin
except Exception:
    Garmin = None


if Garmin is not None and not getattr(Garmin, "_garmin_logger_date_patch", False):
    _original_get_activity = Garmin.get_activity
    _original_get_activities_by_date = Garmin.get_activities_by_date
    _child_parent_dates = {}

    def _extract_date(value):
        if isinstance(value, str) and len(value) >= 10:
            try:
                datetime.strptime(value[:10], "%Y-%m-%d")
                return value[:10]
            except ValueError:
                return None
        return None

    def _child_ids(detail):
        if not isinstance(detail, dict):
            return []
        meta = detail.get("metadataDTO") or {}
        ids = meta.get("childIds") or meta.get("childActivityIds") or detail.get("childIds") or detail.get("childActivityIds") or []
        if isinstance(ids, dict):
            ids = list(ids.values())
        if not isinstance(ids, (list, tuple, set)):
            return []
        return [str(x) for x in ids if x is not None]

    def _remember_parent(detail):
        if not isinstance(detail, dict):
            return
        parent_date = _extract_date(detail.get("startTimeLocal")) or _extract_date(detail.get("startTimeGMT")) or _extract_date(detail.get("startTime"))
        if parent_date:
            for child_id in _child_ids(detail):
                _child_parent_dates[child_id] = parent_date

    def _patched_get_activity(self, activity_id):
        detail = _original_get_activity(self, activity_id)
        activity_key = str(activity_id)
        _remember_parent(detail)
        if isinstance(detail, dict) and activity_key in _child_parent_dates:
            if not detail.get("startTimeLocal") and not detail.get("startTimeGMT") and not detail.get("startTime"):
                detail["startTimeLocal"] = _child_parent_dates[activity_key]
        return detail

    def _patched_get_activities_by_date(self, start, end):
        activities = _original_get_activities_by_date(self, start, end)
        if activities:
            for act in activities:
                if not isinstance(act, dict):
                    continue
                parent_date = _extract_date(act.get("startTimeLocal")) or _extract_date(act.get("startTimeGMT")) or _extract_date(act.get("startTime"))
                if not parent_date:
                    continue
                meta = act.get("metadataDTO") or {}
                ids = meta.get("childIds") or meta.get("childActivityIds") or act.get("childIds") or act.get("childActivityIds") or []
                if isinstance(ids, dict):
                    ids = list(ids.values())
                if isinstance(ids, (list, tuple, set)):
                    for child_id in ids:
                        if child_id is not None:
                            _child_parent_dates[str(child_id)] = parent_date
        return activities

    Garmin.get_activity = _patched_get_activity
    Garmin.get_activities_by_date = _patched_get_activities_by_date
    Garmin._garmin_logger_date_patch = True

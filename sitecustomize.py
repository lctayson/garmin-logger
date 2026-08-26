"""Startup compatibility patches for garmin_to_json.py.

This module is loaded automatically by Python's site machinery. It keeps the
restored helper compatibility shim and also patches Garmin multisport child
activity details so child legs inherit the parent activity's local date when
Garmin omits a date on the child response. That prevents sport-aware training
history from assigning historical swim/bike/run legs to the wrong week.
"""

import builtins
from datetime import datetime, timedelta

from garmin_helpers import (
    get_training_status_details,
    get_metric_trend,
    get_body_battery_trend,
    get_activities,
)

builtins.get_training_status_details = get_training_status_details
builtins.get_metric_trend = get_metric_trend
builtins.get_body_battery_trend = get_body_battery_trend
builtins.get_activities = get_activities

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
        ids = (
            meta.get("childIds")
            or meta.get("childActivityIds")
            or detail.get("childIds")
            or detail.get("childActivityIds")
            or []
        )
        if isinstance(ids, dict):
            ids = list(ids.values())
        if not isinstance(ids, (list, tuple, set)):
            return []
        return [str(x) for x in ids if x is not None]

    def _remember_parent(detail):
        if not isinstance(detail, dict):
            return
        parent_date = (
            _extract_date(detail.get("startTimeLocal"))
            or _extract_date(detail.get("startTimeGMT"))
            or _extract_date(detail.get("startTime"))
        )
        if not parent_date:
            return
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

        # Garmin's exact-date search can occasionally return an empty list for
        # an otherwise valid historical activity. Retry with a one-day buffer
        # on each side and filter by the activity's actual local start date.
        # This fallback is only used when the normal query returns nothing, so
        # we do not call the recent-activities endpoint on every export.
        if not activities and start == end:
            try:
                target = datetime.strptime(start, "%Y-%m-%d").date()
                buffered_start = (target - timedelta(days=1)).isoformat()
                buffered_end = (target + timedelta(days=1)).isoformat()
                candidates = _original_get_activities_by_date(self, buffered_start, buffered_end) or []
                activities = [
                    act for act in candidates
                    if isinstance(act, dict)
                    and (
                        _extract_date(act.get("startTimeLocal"))
                        or _extract_date(act.get("startTimeGMT"))
                        or _extract_date(act.get("startTime"))
                    ) == start
                ]
            except Exception:
                pass

        for act in activities or []:
            if not isinstance(act, dict):
                continue
            parent_date = (
                _extract_date(act.get("startTimeLocal"))
                or _extract_date(act.get("startTimeGMT"))
                or _extract_date(act.get("startTime"))
            )
            if not parent_date:
                continue
            meta = act.get("metadataDTO") or {}
            ids = (
                meta.get("childIds")
                or meta.get("childActivityIds")
                or act.get("childIds")
                or act.get("childActivityIds")
                or []
            )
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

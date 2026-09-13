"""Export raw Garmin activity API responses without interpretation.

This module is intentionally independent from the analysis-oriented JSON
pipeline. It preserves the Garmin API payloads so future analysis can inspect
fields that the normalized output does not currently use.
"""

import argparse
import json
import os
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from garminconnect import Garmin

from config import get_timezone, resolve_timezone


RAW_ROOT = Path("data/raw")

# Activity-specific endpoints exposed by the installed garminconnect client.
# Each response is stored independently and untouched apart from JSON-safe
# serialization. Optional endpoints are allowed to fail because availability
# varies by activity type/device/account.
_ACTIVITY_ENDPOINTS = (
    ("activity", "get_activity"),
    ("activity_splits", "get_activity_splits"),
    ("activity_details", "get_activity_details"),
    ("activity_weather", "get_activity_weather"),
    ("activity_hr_in_timezones", "get_activity_hr_in_timezones"),
)


def _json_safe(value):
    """Return a JSON-serializable copy without changing Garmin field names."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        if isinstance(value, dict):
            return {str(k): _json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [_json_safe(v) for v in value]
        return str(value)


def _activity_date(activity, fallback):
    value = activity.get("startTimeLocal") or activity.get("startTimeGMT") or ""
    if isinstance(value, str) and len(value) >= 10:
        return value[:10]
    return fallback.isoformat()


def _slugify(name):
    """Turn an activity name into a filename-safe slug, e.g. 'Bohol 5150' -> 'bohol-5150'."""
    if not name:
        return None
    normalized = unicodedata.normalize("NFKD", name)
    ascii_str = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_str).strip("-").lower()
    return slug or None


def _fetch_endpoint(api, activity_id, method_name):
    """Call one Garmin endpoint and return its raw response or an error record."""
    method = getattr(api, method_name, None)
    if method is None:
        return {
            "available": False,
            "error": f"Garmin client has no method {method_name}",
        }

    try:
        if method_name == "get_activity_details":
            # Request a large chart payload while disabling the polyline here;
            # GPS/polyline data is not required for the time-series metrics and
            # can make the response unnecessarily large.
            response = method(activity_id, maxchart=10000, maxpoly=0)
        else:
            response = method(activity_id)
        return {"available": True, "data": _json_safe(response)}
    except Exception as exc:
        # Keep the raw export useful even when Garmin does not expose an
        # endpoint for a particular activity. Do not invent or normalize data.
        return {
            "available": True,
            "error": f"{type(exc).__name__}: {exc}",
        }


def export_activity(api, activity, output_root=RAW_ROOT):
    """Save separate raw responses for all supported activity endpoints."""
    activity_id = activity.get("activityId")
    if not activity_id:
        return None

    activity_date = _activity_date(activity, date.today())
    activity_type = activity.get("activityType", {}).get("typeKey") or "unknown"
    slug = _slugify(activity.get("activityName")) or activity_type
    out_dir = Path(output_root) / "activity_details" / activity_date[:4] / activity_date[5:7]
    out_dir.mkdir(parents=True, exist_ok=True)
    # activity_id is kept in the filename (even though the slug carries the
    # readable name) so two same-day activities sharing a generic Garmin
    # auto-name (e.g. "Malolos Running") never collide/overwrite each other.
    path = out_dir / f"{activity_date}_{slug}_{activity_id}.json"

    endpoints = {
        "activities_by_date": {"available": True, "data": _json_safe(activity)},
    }
    for endpoint_name, method_name in _ACTIVITY_ENDPOINTS:
        endpoints[endpoint_name] = _fetch_endpoint(api, activity_id, method_name)

    payload = {
        "source": "Garmin Connect API",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "activity_id": activity_id,
        "activity_date": activity_date,
        "endpoints": endpoints,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def export_date(api, target_date, output_root=RAW_ROOT):
    """Export every activity returned by Garmin for one local date."""
    activities = api.get_activities_by_date(target_date.isoformat(), target_date.isoformat()) or []
    paths = []
    for activity in activities:
        try:
            path = export_activity(api, activity, output_root)
            if path:
                paths.append(path)
        except Exception as exc:
            print(f"Skipping activity {activity.get('activityId')}: {exc}")
    return paths


# Daily (non-activity-specific) endpoints. Each entry captures the raw,
# untouched response so field-name mismatches in the analysis pipeline
# (e.g. garmin_activity_enrichment._running_tolerance) can be debugged
# against real data instead of guessed at.
_RUNNING_TOLERANCE_LOOKBACK_DAYS = 6  # matches _running_tolerance()'s 7-day window


def export_running_tolerance(api, target_date, output_root=RAW_ROOT):
    """Save the raw Running Tolerance response for the 7-day window ending on target_date."""
    start_date = target_date - timedelta(days=_RUNNING_TOLERANCE_LOOKBACK_DAYS)
    out_dir = Path(output_root) / "daily" / "running_tolerance" / f"{target_date.year:04d}" / f"{target_date.month:02d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{target_date.isoformat()}.json"

    method = getattr(api, "get_running_tolerance", None)
    if method is None:
        endpoint = {"available": False, "error": "Garmin client has no method get_running_tolerance"}
    else:
        try:
            response = method(start_date.isoformat(), target_date.isoformat(), aggregation="daily")
            endpoint = {"available": True, "data": _json_safe(response)}
        except Exception as exc:
            endpoint = {"available": True, "error": f"{type(exc).__name__}: {exc}"}

    payload = {
        "source": "Garmin Connect API",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "target_date": target_date.isoformat(),
        "window_start": start_date.isoformat(),
        "window_end": target_date.isoformat(),
        "endpoints": {"running_tolerance": endpoint},
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def main():
    parser = argparse.ArgumentParser(description="Export raw Garmin activity API responses.")
    parser.add_argument("--date", help="Local Garmin activity date (YYYY-MM-DD); defaults to today")
    parser.add_argument("--output-root", default=str(RAW_ROOT))
    parser.add_argument("--timezone", help="IANA timezone override, e.g. Asia/Manila")
    args = parser.parse_args()

    timezone_name = resolve_timezone(args.timezone)
    get_timezone(args.timezone)  # validate configured timezone using the existing project hierarchy
    target_date = date.fromisoformat(args.date) if args.date else date.today()

    tokenstore = os.environ.get("GARMIN_TOKENSTORE", "~/.garminconnect")
    api = Garmin()
    api.login(tokenstore=os.path.expanduser(tokenstore))

    print(f"Using timezone: {timezone_name}")
    paths = export_date(api, target_date, Path(args.output_root))
    print(f"Exported {len(paths)} raw activity response(s).")
    for path in paths:
        print(path)

    tolerance_path = export_running_tolerance(api, target_date, Path(args.output_root))
    print(f"Exported raw running tolerance response: {tolerance_path}")


if __name__ == "__main__":
    main()
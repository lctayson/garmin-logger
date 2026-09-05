"""Export raw Garmin activity API responses without interpretation.

This module is intentionally independent from the analysis-oriented JSON
pipeline. It preserves the Garmin API payload so future analysis can inspect
fields that the normalized output does not currently use.
"""

import argparse
import json
import os
from datetime import date
from pathlib import Path

from garminconnect import Garmin

from config import get_timezone, resolve_timezone


RAW_ROOT = Path("data/raw")


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


def export_activity(api, activity, output_root=RAW_ROOT):
    """Save the complete get_activity() response for one activity."""
    activity_id = activity.get("activityId")
    if not activity_id:
        return None

    detail = api.get_activity(activity_id) or {}
    activity_date = _activity_date(activity, date.today())
    out_dir = Path(output_root) / "activity_details" / activity_date[:4] / activity_date[5:7]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{activity_id}.json"

    payload = {
        "source": "Garmin Connect API",
        "retrieved_at": date.today().isoformat(),
        "activity_id": activity_id,
        "activity_date": activity_date,
        "activity_summary": _json_safe(activity),
        "activity_detail": _json_safe(detail),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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


if __name__ == "__main__":
    main()

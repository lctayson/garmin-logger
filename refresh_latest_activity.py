"""Refresh data/latest_activities.json from Garmin's most recent activity."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from garminconnect import Garmin
from garmin_helpers import get_activities

LOCAL_TZ = ZoneInfo("Asia/Manila")


def activity_date(activity):
    value = activity.get("startTimeLocal") or activity.get("startTimeGMT") or activity.get("startTime")
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(LOCAL_TZ).date().isoformat()
    except ValueError:
        text = str(value)
        return text[:10] if len(text) >= 10 else None


def get_latest_activity_payload(api):
    """Use Garmin's recency-ordered activity endpoint, then fetch our full formatted activity."""
    recent = api.get_activities(0, 1) or []
    if not recent:
        return None
    latest = recent[0]
    date_text = activity_date(latest)
    if not date_text:
        return None
    activities = get_activities(api, date_text)
    activity_id = latest.get("activityId")
    if activities:
        for activity in activities:
            if activity.get("activityId") == activity_id:
                return {"date": date_text, "activities": [activity]}
        return {"date": date_text, "activities": [activities[0]]}
    return None


def refresh(api, data_dir):
    payload = get_latest_activity_payload(api)
    if not payload or not payload.get("activities"):
        return False
    path = os.path.join(data_dir, "latest_activities.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args()
    token_dir = os.environ.get("GARMIN_TOKENSTORE", "./.garminconnect")
    api = Garmin()
    api.login(token_dir)
    if refresh(api, args.data_dir):
        print("[latest_activity] Refreshed latest_activities.json from Garmin's newest activity")
    else:
        print("[latest_activity] No recent activity returned; keeping existing latest_activities.json")


if __name__ == "__main__":
    main()

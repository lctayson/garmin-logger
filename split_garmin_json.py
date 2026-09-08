#!/usr/bin/env python3
"""
Split the consolidated Garmin JSON into the dated metrics and activities files.
"""

import argparse
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Asia/Manila")


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload


def write_json(path, payload, activity_compact=False):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        if activity_compact:
            json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def split_payload(payload):
    metrics = {k: v for k, v in payload.items() if k != "activities"}
    activities = payload.get("activities", [])
    return metrics, activities


def normalize_activity(activity):
    """Remove legacy root fields and put the activity in stable output order."""
    if not isinstance(activity, dict):
        return activity

    out = dict(activity)
    for key in ("duration_min", "aerobic_te", "anaerobic_te", "training_effect_label"):
        out.pop(key, None)

    priority = (
        "name", "activity_id", "type",
        "distance", "time", "elapsed_time", "moving_time", "avg_pace", "gap",
        "avg_hr", "max_hr", "recovery_hr", "elevation_gain", "elevation_loss",
        "load", "start_time_local", "training_effect", "interval_drift", "decoupling",
        "splits", "weather", "hr_zones", "power_zones", "lap_count",
    )
    ordered = {}
    for key in priority:
        if key in out and out[key] is not None:
            ordered[key] = out[key]
    for key, value in out.items():
        if key not in ordered and value is not None:
            ordered[key] = value
    return ordered


def normalize_activities(activities):
    return [normalize_activity(activity) for activity in (activities or [])]


def refresh_latest_activities(data_dir, target_date, current_path, has_activity, today):
    """Refresh latest_activities.json only when today's export contains an activity."""
    if not has_activity or target_date != today:
        return False

    latest_path = os.path.join(data_dir, "latest_activities.json")
    with open(current_path, "r", encoding="utf-8") as src:
        payload = json.load(src)
    write_json(latest_path, payload, activity_compact=False)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--input", default=None)
    args = parser.parse_args()

    today = datetime.now(LOCAL_TZ).date()
    target_date = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else today
    input_path = args.input or os.path.join(args.data_dir, "latest.json")
    payload = load_json(input_path)
    metrics, activities = split_payload(payload)
    activities = normalize_activities(activities)

    dated_metrics = os.path.join(args.data_dir, f"metrics_{target_date:%Y-%m-%d}.json")
    dated_activities = os.path.join(args.data_dir, f"activities_{target_date:%Y-%m-%d}.json")
    write_json(dated_metrics, metrics)
    write_json(dated_activities, {"date": target_date.isoformat(), "units": payload.get("units", {}), "activities": activities}, activity_compact=False)
    refresh_latest_activities(args.data_dir, target_date, dated_activities, bool(activities), today)


if __name__ == "__main__":
    main()

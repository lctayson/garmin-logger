"""Split and compact the generated Garmin snapshot."""
from __future__ import annotations
import argparse
import json
import os
import shutil
from datetime import datetime

ACTIVITY_KEYS = ("activities", "activity_data", "activityData")
TREND_KEYS = ("training_history", "trend_recent_daily", "trend_long_range_weekly", "body_battery_trend")

KEY_MAP = {
    "resting_heart_rate": "resting_hr", "total_steps": "steps", "total_sleep_hours": "sleep_hours",
    "7_day_distance_km": "7d_distance_km", "28_day_avg_weekly_distance_km": "28d_avg_weekly_distance_km",
    "weekly_distance_last_4_weeks_km": "weekly_distance_4w_km", "last_night_avg_ms": "last_night_avg_ms",
    "seven_day_avg_ms": "7d_avg_ms", "acute_training_load": "acute_load", "recovery_time_hours": "recovery_hours",
    "activityId": "activity_id", "duration_mins": "duration_min", "average_heart_rate": "avg_hr", "average_hr": "avg_hr",
    "aerobic_training_effect": "aerobic_te", "anaerobic_training_effect": "anaerobic_te", "exercise_load": "load",
    "activity_splits": "splits", "parentActivityId": "parent_activity_id", "avg_gct_ms": "ground_contact_ms",
    "avg_stride_length_m": "stride_length_m", "intensityType": "intensity",
}

def compact_keys(obj):
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            new_key = KEY_MAP.get(key, key)
            if new_key in out and new_key != key:
                raise ValueError(f"Key collision while compacting: {key} -> {new_key}")
            out[new_key] = compact_keys(value)
        return out
    if isinstance(obj, list):
        return [compact_keys(item) for item in obj]
    return obj

def to_columnar(rows):
    if not isinstance(rows, list) or not rows or not all(isinstance(row, dict) for row in rows):
        return rows
    columns = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    return {"columns": columns, "data": [[row.get(column) for column in columns] for row in rows]}

def compact_activity(activity):
    activity = compact_keys(activity)
    split_key = next((key for key in ("splits", "laps") if key in activity), None)
    if split_key:
        activity[split_key] = to_columnar(activity[split_key])
    return activity

def compact_activities(value):
    if not isinstance(value, list):
        return value
    return [compact_activity(activity) if isinstance(activity, dict) else activity for activity in value]

def compact_trends(value):
    if isinstance(value, list):
        return to_columnar(compact_keys(value))
    return compact_keys(value)

def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload

def split_payload(payload):
    activity_key = next((key for key in ACTIVITY_KEYS if key in payload), None)
    if activity_key is None:
        raise KeyError("Could not find the activity section")
    trend_keys_present = [key for key in TREND_KEYS if key in payload]
    daily = {key: value for key, value in payload.items() if key != activity_key and key not in trend_keys_present}
    metrics = {"date": payload.get("date"), "daily": compact_keys(daily)}
    metrics.update({key: compact_trends(payload[key]) for key in trend_keys_present})
    activities = {"date": payload.get("date"), "activities": compact_activities(payload.get(activity_key))}
    return metrics, activities

def _compact_data_arrays(text):
    marker = '"data": ['
    search_from = 0
    while True:
        marker_pos = text.find(marker, search_from)
        if marker_pos < 0:
            break
        array_start = marker_pos + len('"data": ')
        depth = 0
        in_string = False
        escaped = False
        array_end = None
        for i in range(array_start, len(text)):
            ch = text[i]
            if in_string:
                if escaped: escaped = False
                elif ch == "\\": escaped = True
                elif ch == '"': in_string = False
                continue
            if ch == '"': in_string = True
            elif ch == '[': depth += 1
            elif ch == ']':
                depth -= 1
                if depth == 0:
                    array_end = i
                    break
        if array_end is None: break
        rows = json.loads(text[array_start:array_end + 1])
        indent = len(text[:marker_pos].rsplit("\n", 1)[-1])
        row_indent = " " * (indent + 2)
        row_text = "[\n" + ",\n".join(row_indent + json.dumps(row, ensure_ascii=False, separators=(", ", ": ")) for row in rows) + "\n" + " " * indent + "]"
        text = text[:array_start] + row_text + text[array_end + 1:]
        search_from = array_start + len(row_text)
    return text

def _minified_root_lines(payload):
    lines = ["{"]
    items = list(payload.items())
    for index, (key, value) in enumerate(items):
        comma = "," if index < len(items) - 1 else ""
        lines.append(f"  {json.dumps(key, ensure_ascii=False)}: {json.dumps(value, ensure_ascii=False, separators=(",", ":"))}{comma}")
    lines.append("}")
    return "\n".join(lines)

def write_json(path, payload, activity_compact=False, root_minified=False):
    tmp = f"{path}.tmp"
    if root_minified:
        text = _minified_root_lines(payload)
    else:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if activity_compact:
            text = _compact_data_arrays(text)
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    os.replace(tmp, path)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None)
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args()
    latest_path = os.path.join(args.data_dir, "latest.json")
    if not os.path.isfile(latest_path):
        raise FileNotFoundError(f"Missing generated file: {latest_path}")
    payload = load_json(latest_path)
    target_date = args.date or payload.get("date")
    if not target_date: raise ValueError("Target date is missing")
    target_date = datetime.strptime(target_date, "%Y-%m-%d").date()
    if payload.get("date") and payload["date"] != target_date.isoformat():
        raise ValueError(f"Date mismatch: --date={target_date.isoformat()} but JSON date={payload['date']}")
    metrics, activities = split_payload(payload)
    month_dir = os.path.join(args.data_dir, f"{target_date.year:04d}", f"{target_date.month:02d}")
    os.makedirs(month_dir, exist_ok=True)
    dated_metrics = os.path.join(month_dir, f"{target_date.isoformat()}_metrics.json")
    dated_activities = os.path.join(month_dir, f"{target_date.isoformat()}_activities.json")
    write_json(dated_metrics, metrics, root_minified=True)
    write_json(dated_activities, activities, activity_compact=True)
    shutil.copyfile(dated_metrics, os.path.join(args.data_dir, "latest_metrics.json"))
    shutil.copyfile(dated_activities, os.path.join(args.data_dir, "latest_activities.json"))
    for old_name in ("latest_daily.json", "latest_trends.json"):
        old_path = os.path.join(args.data_dir, old_name)
        if os.path.exists(old_path): os.remove(old_path)
    for old_suffix in ("_daily.json", "_trends.json"):
        old_path = os.path.join(month_dir, f"{target_date.isoformat()}{old_suffix}")
        if os.path.exists(old_path): os.remove(old_path)
    old_dated = os.path.join(month_dir, f"{target_date.isoformat()}.json")
    if os.path.exists(old_dated): os.remove(old_dated)
    os.remove(latest_path)

if __name__ == "__main__": main()

import os
import sys
import json
import argparse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from garminconnect import Garmin
from garmin_helpers import (
    get_training_status_details,
    get_body_battery_trend,
    get_activities,
)
from sport_trends import get_metric_trend


def safe_float(val, decimals=2):
    if val is None or val == "N/A" or val == "":
        return None
    try:
        return round(float(val), decimals)
    except (ValueError, TypeError):
        return None


def safe_int(val):
    if val is None or val == "N/A" or val == "":
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def deep_get(source_dict, keys, default=None):
    if not isinstance(source_dict, dict):
        return default
    for key in keys:
        if "." in key:
            parts = key.split(".")
            val = source_dict
            for part in parts:
                if isinstance(val, dict) and part in val:
                    val = val.get(part)
                else:
                    val = None
                    break
            if val is not None and val != "":
                return val
        else:
            if key in source_dict:
                val = source_dict.get(key)
                if val is not None and val != "":
                    return val
    return default


def format_pace(distance_m, duration_sec, activity_type="run"):
    """Format pace as MM:SS (per km for run/walk, per 100m for swim). Returns None for cycling/others."""
    if not distance_m or not duration_sec or distance_m <= 0 or duration_sec <= 0:
        return None
    activity_type_lower = (activity_type or "").lower()
    if "swim" in activity_type_lower:
        sec_per_unit = (duration_sec / distance_m) * 100
    elif any(t in activity_type_lower for t in ["cycle", "biking", "bike"]):
        return None
    else:
        sec_per_unit = (duration_sec / distance_m) * 1000
    total_sec = int(round(sec_per_unit))
    return f"{total_sec // 60}:{total_sec % 60:02d}"


def _history_sport(act):
    raw = deep_get(act, ["activityType.typeKey", "activityType", "sport", "sportType", "type"], "") or ""
    raw = str(raw).lower()
    if "run" in raw or "jog" in raw:
        return "running"
    if any(x in raw for x in ("cycl", "bike", "biking")):
        return "cycling"
    if "swim" in raw:
        return "swimming"
    if any(x in raw for x in ("multi", "triathlon", "duathlon", "aquathlon")):
        return "multisport"
    if "transition" in raw:
        return "transition"
    return "other"


def _history_date(act, fallback):
    value = act.get("startTimeLocal") or act.get("startTimeGMT") or act.get("startTime") or ""
    if isinstance(value, str) and len(value) >= 10:
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
    return fallback


def _history_distance_km(act):
    if act.get("distance_km") is not None:
        return float(act.get("distance_km") or 0)
    return float(act.get("distance") or 0) / 1000.0


def _history_duration_hours(act):
    if act.get("duration_mins") is not None:
        return float(act.get("duration_mins") or 0) / 60.0
    duration = act.get("duration") or act.get("elapsedDuration") or act.get("movingDuration") or 0
    return float(duration or 0) / 3600.0


def _history_load(act):
    value = deep_get(act, [
        "exerciseLoad", "trainingLoad", "activityTrainingLoad",
        "activityTrainingLoadDTO.trainingLoad", "summaryDTO.trainingLoad",
        "summaryDTO.exerciseLoad", "activityTrainingLoadDTO.exerciseLoad"
    ])
    return safe_float(value, 1)


def _history_empty():
    return {"activity_count": 0, "distance_km": 0.0, "duration_hours": 0.0, "exercise_load": 0.0, "exercise_load_available": False}


def _history_add(bucket, act):
    bucket["activity_count"] += 1
    bucket["distance_km"] += _history_distance_km(act)
    bucket["duration_hours"] += _history_duration_hours(act)
    load = _history_load(act)
    if load is not None:
        bucket["exercise_load"] += load
        bucket["exercise_load_available"] = True


def _history_finalize(bucket):
    out = {"activity_count": bucket["activity_count"], "distance_km": round(bucket["distance_km"], 2), "duration_hours": round(bucket["duration_hours"], 2)}
    if bucket.get("exercise_load_available"):
        out["exercise_load"] = round(bucket["exercise_load"], 1)
    return out


def _history_expand_multisport(api, activities):
    """Expand multisport parents into child legs for sport-specific volume."""
    expanded = []
    for act in activities or []:
        if _history_sport(act) != "multisport" or not act.get("activityId"):
            expanded.append(act)
            continue
        try:
            detail = api.get_activity(act["activityId"])
            meta = detail.get("metadataDTO", {}) if isinstance(detail, dict) else {}
            child_ids = meta.get("childIds") or meta.get("childActivityIds") or detail.get("childIds") or detail.get("childActivityIds") or []
            if isinstance(child_ids, dict):
                child_ids = list(child_ids.values())
        except Exception:
            child_ids = []
        if not child_ids:
            expanded.append(act)
            continue
        for child_id in child_ids:
            try:
                detail = api.get_activity(child_id)
            except Exception:
                continue
            summary = detail.get("summaryDTO", {}) if isinstance(detail, dict) else {}
            typ = deep_get(detail, ["activityTypeDTO.typeKey", "activityType.typeKey", "activityType"], "") or ""
            expanded.append({
                "activityId": child_id,
                "activityType": {"typeKey": typ},
                "distance": summary.get("distance") or detail.get("distance") or 0,
                "duration": summary.get("duration") or detail.get("duration") or 0,
                "exerciseLoad": deep_get(summary, ["trainingLoad", "exerciseLoad"]) or deep_get(detail, ["trainingLoad", "exerciseLoad", "activityTrainingLoad"]),
            })
    return expanded


def get_training_history(api, target_date):
    """Build sport-aware 7-day/28-day training history."""
    start_history_date = target_date - timedelta(days=27)
    try:
        historical_activities = api.get_activities_by_date(start_history_date.isoformat(), target_date.isoformat())
    except Exception:
        historical_activities = []
    historical_activities = _history_expand_multisport(api, historical_activities)
    by_date = {}
    for act in historical_activities:
        d = _history_date(act, target_date)
        by_date.setdefault(d, []).append(act)
    sports = ("running", "cycling", "swimming", "multisport", "other", "transition")

    def window(start_date, end_date):
        buckets = {s: _history_empty() for s in sports}
        for d, acts in by_date.items():
            if start_date <= d <= end_date:
                for act in acts:
                    _history_add(buckets[_history_sport(act)], act)
        total = _history_empty()
        for bucket in buckets.values():
            total["activity_count"] += bucket["activity_count"]
            total["distance_km"] += bucket["distance_km"]
            total["duration_hours"] += bucket["duration_hours"]
            if bucket.get("exercise_load_available"):
                total["exercise_load"] += bucket["exercise_load"]
                total["exercise_load_available"] = True
        return buckets, total

    seven_start = target_date - timedelta(days=6)
    seven_sport, seven_total = window(seven_start, target_date)
    weekly = []
    for i in range(4):
        week_end = target_date - timedelta(days=i * 7)
        week_start = week_end - timedelta(days=6)
        buckets, total = window(week_start, week_end)
        weekly.append({
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "total_endurance": _history_finalize(total),
            "sports": {s: _history_finalize(buckets[s]) for s in sports if buckets[s]["activity_count"] > 0}
        })
    weekly.reverse()
    sport_7 = {s: _history_finalize(seven_sport[s]) for s in sports if seven_sport[s]["activity_count"] > 0}
    total_7 = _history_finalize(seven_total)
    running_weekly = [w["sports"].get("running", {}).get("distance_km", 0.0) for w in weekly]
    running_avg = round(sum(running_weekly) / len(running_weekly), 1) if running_weekly else 0.0
    return {
        "7_day": {"total_endurance": total_7, "sports": sport_7},
        "28_day": {"avg_weekly_running_distance_km": running_avg, "weekly_total_endurance": weekly},
        "legacy_running_summary": {
            "7_day_distance_km": sport_7.get("running", {}).get("distance_km", 0.0),
            "28_day_avg_weekly_distance_km": running_avg,
            "weekly_distance_last_4_weeks_km": running_weekly
        }
    }


def get_health_stats(api, target_date_str):
    """Fetch and format daily health stats: resting HR, HRV, sleep."""
    stats = {}
    try:
        stats = api.get_stats(target_date_str)
    except Exception:
        pass
    rhr = safe_int(stats.get("restingHeartRate") or stats.get("rhr"))
    total_steps = safe_int(stats.get("totalSteps") or stats.get("steps"))
    sleep_data = {}
    try:
        sleep_data = api.get_sleep_data(target_date_str)
    except Exception:
        pass
    sleep_dto = sleep_data.get("dailySleepDTO", {}) if isinstance(sleep_data, dict) else {}
    sleep_score = safe_int(sleep_dto.get("sleepScores", {}).get("overall", {}).get("value") or sleep_dto.get("overallSleepScore") or sleep_dto.get("sleepScore"))
    sleep_seconds = sleep_dto.get("sleepTimeSeconds")
    sleep_hours = safe_float((sleep_seconds or 0) / 3600 if sleep_seconds else None, 2)
    hrv_data = {}
    try:
        hrv_data = api.get_hrv_data(target_date_str)
    except Exception:
        pass
    hrv_summary = hrv_data.get("hrvSummary", {}) if isinstance(hrv_data, dict) else {}
    hrv_last_night = safe_float(hrv_summary.get("lastNightAvg") or hrv_summary.get("lastNight5MinHigh") or hrv_summary.get("weeklyAvg"), 1)
    hrv_weekly = safe_float(hrv_summary.get("weeklyAvg"), 1)
    hrv_status = hrv_summary.get("status")
    return {
        "resting_heart_rate": rhr,
        "total_steps": total_steps,
        "sleep_score": sleep_score,
        "sleep_hours": sleep_hours,
        "hrv_last_night_avg_ms": hrv_last_night,
        "hrv_7_day_avg_ms": hrv_weekly,
        "hrv_status": hrv_status,
    }


def build_priority_metrics(health_stats, training_status):
    """Build a compact, high-priority snapshot from already-fetched data."""
    ts = training_status or {}
    return {
        "resting_hr_bpm": health_stats.get("resting_heart_rate"),
        "hrv_last_night_avg_ms": health_stats.get("hrv_last_night_avg_ms"),
        "hrv_7_day_avg_ms": health_stats.get("hrv_7_day_avg_ms"),
        "hrv_status": health_stats.get("hrv_status"),
        "sleep_hours": health_stats.get("sleep_hours"),
        "sleep_score": health_stats.get("sleep_score"),
        "training_status": ts.get("training_status"),
        "acute_load": ts.get("acute_load"),
        "chronic_load": ts.get("chronic_load"),
        "acwr": ts.get("acwr"),
        "vo2_max": ts.get("vo2_max"),
        "recovery_time_hours": ts.get("recovery_time_hours"),
    }


def strip_volatile_fields(payload):
    """Return payload without generation timestamp for meaningful-change comparison."""
    if not isinstance(payload, dict):
        return payload
    cleaned = dict(payload)
    cleaned.pop("generated_at_local", None)
    return cleaned


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", dest="date", default=None, help="Target date YYYY-MM-DD")
    parser.add_argument("--trend-days", type=int, default=7)
    parser.add_argument("--trend-weeks", type=int, default=12)
    parser.add_argument("--body-battery-days", type=int, default=7)
    args = parser.parse_args()

    ph_today = datetime.now(ZoneInfo("Asia/Manila")).date().isoformat()
    target_date_str = args.date or ph_today
    target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()

    api = Garmin(os.getenv("GARMIN_EMAIL"), os.getenv("GARMIN_PASSWORD"))
    api.login()

    health_stats = get_health_stats(api, target_date_str)
    training_status = get_training_status_details(api, target_date_str)
    activities = get_activities(api, target_date_str)
    priority_metrics = build_priority_metrics(health_stats, training_status)

    payload = {
        "date": target_date_str,
        "priority_metrics": priority_metrics,
        "health_stats": health_stats,
        "training_status": training_status,
        "activities": activities,
    }

    training_history = get_training_history(api, target_date)
    payload["training_history"] = training_history

    if args.trend_days > 0:
        payload["trend_recent_daily"] = get_metric_trend(api, target_date, days=args.trend_days, interval=1)
    if args.trend_weeks > 0:
        payload["trend_long_range_weekly"] = get_metric_trend(api, target_date, days=args.trend_weeks * 7, interval=7)
    if args.body_battery_days > 0:
        payload["body_battery_trend"] = get_body_battery_trend(api, target_date, days=args.body_battery_days)

    payload["generated_at_local"] = datetime.now(ZoneInfo("Asia/Manila")).isoformat(timespec="minutes")

    os.makedirs("data", exist_ok=True)
    file_path = os.path.join("data", f"{target_date_str}.json")
    existing_payload = None
    if os.path.exists(file_path):
        try:
            with open(file_path) as f:
                existing_payload = json.load(f)
        except Exception:
            existing_payload = None

    changed = existing_payload is None or strip_volatile_fields(existing_payload) != strip_volatile_fields(payload)
    if changed:
        with open(file_path, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"Successfully generated/updated Garmin JSON at: {file_path}")
    else:
        print(f"No meaningful change since last run -- leaving {file_path} unchanged")

    if target_date_str == ph_today:
        latest_path = os.path.join("data", "latest.json")
        existing_latest = None
        if os.path.exists(latest_path):
            try:
                with open(latest_path) as f:
                    existing_latest = json.load(f)
            except Exception:
                existing_latest = None
        latest_changed = existing_latest is None or strip_volatile_fields(existing_latest) != strip_volatile_fields(payload)
        if latest_changed:
            with open(latest_path, "w") as f:
                json.dump(payload, f, indent=2)
            print(f"Successfully generated/updated latest Garmin data at: {latest_path}")
        else:
            print(f"No meaningful change since last run -- leaving {latest_path} unchanged")
    else:
        print(f"Historical date {target_date_str} != current Philippines date {ph_today}; skipping data/latest.json update.")


if __name__ == "__main__":
    main()

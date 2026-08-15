import os
import sys
import json
import argparse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from garminconnect import Garmin

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
    mins = total_sec // 60
    secs = total_sec % 60
    return f"{mins}:{secs:02d}"

def get_training_history(api, target_date):
    """Fetch and calculate training history distance metrics over the past 28 days."""
    start_history_date = target_date - timedelta(days=27)
    try:
        historical_activities = api.get_activities_by_date(
            start_history_date.isoformat(),
            target_date.isoformat()
        )
    except Exception:
        historical_activities = []

    running_activities = []
    for act in historical_activities:
        act_type = deep_get(act, ["activityType.typeKey", "activityType"], "").lower()
        if "run" in act_type:
            start_str = act.get("startTimeLocal", "")
            try:
                act_date = datetime.strptime(start_str.split(" ")[0], "%Y-%m-%d").date()
                dist_km = (act.get("distance", 0) or 0) / 1000.0
                running_activities.append({"date": act_date, "distance_km": dist_km})
            except Exception:
                pass

    seven_days_ago = target_date - timedelta(days=6)
    dist_7_days = sum(a["distance_km"] for a in running_activities if seven_days_ago <= a["date"] <= target_date)

    weekly_distances = []
    for i in range(4):
        week_end = target_date - timedelta(days=i * 7)
        week_start = week_end - timedelta(days=6)
        w_dist = sum(a["distance_km"] for a in running_activities if week_start <= a["date"] <= week_end)
        weekly_distances.append(round(w_dist, 1))

    weekly_distances.reverse()
    avg_28_day_weekly = round(sum(weekly_distances) / len(weekly_distances), 1) if weekly_distances else 0.0

    return {
        "7_day_distance_km": round(dist_7_days, 1),
        "28_day_avg_weekly_distance_km": avg_28_day_weekly,
        "weekly_distance_last_4_weeks_km": weekly_distances
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
    sleep_score = safe_int(
        sleep_dto.get("sleepScores", {}).get("overall", {}).get("value") or
        sleep_dto.get("overallSleepScore") or
        sleep_dto.get("sleepScore")
    )
    sleep_duration_sec = sleep_dto.get("sleepTimeSeconds") or sleep_dto.get("durationInSeconds")
    total_sleep_hours = round(sleep_duration_sec / 3600.0, 2) if sleep_duration_sec else None

    deep_sec = sleep_dto.get("deepSleepSeconds")
    light_sec = sleep_dto.get("lightSleepSeconds")
    rem_sec = sleep_dto.get("remSleepSeconds")
    awake_sec = sleep_dto.get("awakeSleepSeconds")

    sleep_stages_hours = {
        "deep": round(deep_sec / 3600.0, 2) if deep_sec is not None else None,
        "light": round(light_sec / 3600.0, 2) if light_sec is not None else None,
        "rem": round(rem_sec / 3600.0, 2) if rem_sec is not None else None,
        "awake": round(awake_sec / 3600.0, 2) if awake_sec is not None else None
    }

    hrv_last, hrv_weekly_avg, hrv_status, baseline_balanced_range = None, None, None, None
    try:
        hrv_data = api.get_hrv_data(target_date_str)
        hrv_summary = hrv_data.get("hrvSummary", {}) if isinstance(hrv_data, dict) else {}
        hrv_status = hrv_summary.get("status") or hrv_summary.get("hrvStatus")
        hrv_last = safe_int(hrv_summary.get("lastNightAvg") or hrv_summary.get("weeklyAvg"))
        hrv_weekly_avg = safe_int(hrv_summary.get("weeklyAvg") or hrv_summary.get("sevenDayAvg") or hrv_summary.get("lastSevenDaysAvg"))

        baseline_obj = hrv_summary.get("baseline", {})
        if isinstance(baseline_obj, dict):
            low_upper = safe_int(baseline_obj.get("lowUpper"))
            balanced_low = safe_int(baseline_obj.get("balancedLow"))
            balanced_upper = safe_int(baseline_obj.get("balancedUpper"))
            marker_value = safe_float(baseline_obj.get("markerValue"), 7)
            baseline_balanced_range = {
                "lowUpper": low_upper,
                "balancedLow": balanced_low,
                "balancedUpper": balanced_upper,
                "markerValue": marker_value
            }
    except Exception:
        pass

    return {
        "resting_heart_rate": rhr,
        "hrv": {
            "last_night_avg_ms": hrv_last,
            "seven_day_avg_ms": hrv_weekly_avg,
            "status": hrv_status,
            "baseline_balanced_range": baseline_balanced_range
        },
        "sleep_score": sleep_score,
        "total_sleep_hours": total_sleep_hours,
        "sleep_stages_hours": {k: v for k, v in sleep_stages_hours.items() if v is not None},
        "total_steps": total_steps
    }

# ... existing helper functions unchanged ...

# The remainder of the file is preserved verbatim except for the latest.json
# handling in main().

def strip_volatile_fields(payload):
    """Return a copy of payload with fields that intentionally change on every
    run but don't reflect any real new data (e.g. the run timestamp) removed,
    so two payloads can be compared for MEANINGFUL change."""
    stripped = dict(payload)
    stripped.pop("generated_at_local", None)
    return stripped

def main():
    ph_today = datetime.now(ZoneInfo("Asia/Manila")).strftime("%Y-%m-%d")

    parser = argparse.ArgumentParser(description="Fetch Garmin data with Garmin export-aligned lap splits.")
    parser.add_argument("--date", type=str, default=ph_today, help="Date in YYYY-MM-DD format")
    parser.add_argument("--trend-days", type=int, default=7,
                         help="Number of trailing days for the DAILY trend series "
                              "(RHR/HRV/sleep -- noisy metrics that need daily resolution). "
                              "Set to 0 to skip.")
    parser.add_argument("--trend-weeks", type=int, default=12,
                         help="Number of trailing weeks for the WEEKLY-sampled long-range trend "
                              "(VO2max/chronic load -- slow-moving metrics, weekly resolution is "
                              "sufficient and far cheaper on API calls). Set to 0 to skip.")
    parser.add_argument("--body-battery-days", type=int, default=7,
                         help="Number of trailing days to include in the Body Battery trend. "
                              "Set to 0 to skip.")
    args = parser.parse_args()
    target_date_str = args.date

    try:
        target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    except ValueError as e:
        raise ValueError(f"Invalid date format provided: '{target_date_str}'. Please use YYYY-MM-DD format.") from e

    garmin_tokens_json = os.environ.get("GARMIN_TOKENS_JSON")
    if not garmin_tokens_json:
        raise ValueError("GARMIN_TOKENS_JSON environment variable is missing.")

    token_dir = "./.garminconnect"
    os.makedirs(token_dir, exist_ok=True)
    with open(os.path.join(token_dir, "garmin_tokens.json"), "w") as f:
        f.write(garmin_tokens_json)

    api = Garmin()
    api.login(token_dir)

    training_history = get_training_history(api, target_date)
    health_stats = get_health_stats(api, target_date_str)
    training_status = get_training_status_details(api, target_date_str)
    activities = get_activities(api, target_date_str)

    payload = {
        "date": target_date_str,
        "generated_at_local": datetime.now(ZoneInfo("Asia/Manila")).isoformat(timespec="minutes"),
        "training_history": training_history,
        "health_stats": health_stats,
        "training_status": training_status,
        "activities": activities
    }

    if args.trend_days > 0:
        payload["trend_recent_daily"] = get_metric_trend(api, target_date, days=args.trend_days, interval=1)

    if args.trend_weeks > 0:
        payload["trend_long_range_weekly"] = get_metric_trend(
            api, target_date, days=args.trend_weeks * 7, interval=7
        )

    if args.body_battery_days > 0:
        payload["body_battery_trend"] = get_body_battery_trend(api, target_date, days=args.body_battery_days)

    os.makedirs("data", exist_ok=True)
    file_path = os.path.join("data", f"{target_date_str}.json")

    existing_payload = None
    if os.path.exists(file_path):
        try:
            with open(file_path) as f:
                existing_payload = json.load(f)
        except Exception:
            existing_payload = None

    if existing_payload is not None and strip_volatile_fields(existing_payload) == strip_volatile_fields(payload):
        print(
            f"No meaningful change since last run (only generated_at_local would differ) -- "
            f"skipping write to keep git history clean: {file_path}"
        )
    else:
        with open(file_path, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"Successfully generated Garmin JSON at: {file_path}")

    # Only refresh data/latest.json when generating data for the current
    # calendar date in the Philippines. Historical requests must NEVER
    # overwrite the current/latest snapshot.
    if target_date_str == ph_today:
        latest_path = os.path.join("data", "latest.json")
        with open(latest_path, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"Successfully generated latest Garmin data at: {latest_path}")
    else:
        print(
            f"Historical date {target_date_str} != current Philippines date {ph_today}; "
            "skipping data/latest.json update."
        )

if __name__ == "__main__":
    main()

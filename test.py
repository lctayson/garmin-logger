import os
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

def get_health_metrics(api, target_date_str):
    """Fetch and format health metrics including HRV weekly average and VO2 max."""
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

    vo2_max = None
    try:
        max_metrics = api.get_max_metrics(target_date_str)
        if isinstance(max_metrics, list) and len(max_metrics) > 0:
            m_item = max_metrics[0]
            vo2_max = safe_float(deep_get(m_item, ["vo2MaxValue", "vo2Max", "generic.vo2MaxValue"]))
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
        "training_status": {
            "vo2_max": vo2_max
        },
        "sleep_score": sleep_score,
        "total_sleep_hours": total_sleep_hours,
        "sleep_stages_hours": {k: v for k, v in sleep_stages_hours.items() if v is not None},
        "total_steps": total_steps
    }

def get_activity_splits(api, activity_id, activity_type="run"):
    """Fetch and format activity splits lap list aligned with Garmin Connect export headers."""
    try:
        splits = api.get_activity_splits(activity_id)
    except Exception:
        splits = {}

    lap_dtos_raw = splits.get("lapDTOs", []) if isinstance(splits, dict) else []
    lap_dtos = []
    cumulative_sec = 0.0

    for lap in lap_dtos_raw:
        lap_distance_m = lap.get("distance", 0) or 0
        lap_duration_sec = lap.get("duration", 0) or lap.get("elapsedDuration", 0) or 0
        cumulative_sec += lap_duration_sec

        distance_km = round(lap_distance_m / 1000.0, 3) if lap_distance_m else 0.0
        time_min = round(lap_duration_sec / 60.0, 2) if lap_duration_sec else 0.0
        cumulative_time_min = round(cumulative_sec / 60.0, 2)
        
        lap_pace = format_pace(lap_distance_m, lap_duration_sec, activity_type)

        max_speed = lap.get("maxSpeed") or lap.get("maximumSpeed")
        best_pace = None
        if max_speed and max_speed > 0:
            best_sec_per_km = (1000.0 / float(max_speed))
            b_mins = int(best_sec_per_km // 60)
            b_secs = int(round(best_sec_per_km % 60))
            best_pace = f"{b_mins}:{b_secs:02d}"

        moving_duration_sec = lap.get("movingDuration") or lap_duration_sec
        moving_time_min = round(moving_duration_sec / 60.0, 2) if moving_duration_sec else None
        avg_moving_pace = format_pace(lap_distance_m, moving_duration_sec, activity_type)

        raw_stride = safe_float(lap.get("strideLength") or lap.get("avgStrideLength"))
        avg_stride_length_m = None
        if raw_stride is not None:
            avg_stride_length_m = round(raw_stride / 100.0, 4) if raw_stride > 3 else round(raw_stride, 4)

        raw_vo = safe_float(lap.get("verticalOscillation") or lap.get("avgVerticalOscillation"))
        vertical_oscillation_cm = None
        if raw_vo is not None:
            vertical_oscillation_cm = round(raw_vo / 10.0, 2) if raw_vo > 20 else round(raw_vo, 2)

        lap_obj = {
            "lap": safe_int(lap.get("lapIndex") or lap.get("splitIndex") or lap.get("lap")),
            "distance_km": distance_km,
            "time_min": time_min,
            "cumulative_time_min": cumulative_time_min,
            "moving_time_min": moving_time_min,
            "avg_pace": lap_pace,
            "avg_moving_pace": avg_moving_pace,
            "best_pace": best_pace,
            "avg_hr": safe_int(lap.get("averageHR") or lap.get("avgHR")),
            "max_hr": safe_int(lap.get("maxHR") or lap.get("maximumHR")),
            "calories": safe_int(lap.get("calories")),
            "avg_power_w": safe_int(lap.get("averagePower") or lap.get("avgPower") or lap.get("power")),
            "normalized_power_w": safe_int(lap.get("normalizedPower") or lap.get("normPower") or lap.get("averagePower") or lap.get("avgPower")),
            "cadence_spm": safe_int(lap.get("averageRunCadence") or lap.get("avgRunCadence") or lap.get("cadence") or lap.get("avgCadence")),
            "max_cadence_spm": safe_int(lap.get("maxRunCadence") or lap.get("maximumRunCadence") or lap.get("maxCadence")),
            "avg_gct_ms": safe_float(lap.get("groundContactTime") or lap.get("avgGroundContactTime") or lap.get("gct"), 1),
            "avg_stride_length_m": avg_stride_length_m,
            "vertical_oscillation_cm": vertical_oscillation_cm,
            "vertical_ratio_pct": safe_float(lap.get("verticalRatio") or lap.get("avgVerticalRatio") or lap.get("vertRatio"), 2),
            "elevation_gain_m": safe_float(lap.get("elevationGain") or lap.get("sumElevationGain") or lap.get("ascent"), 1),
            "elevation_loss_m": safe_float(lap.get("elevationLoss") or lap.get("sumElevationLoss") or lap.get("descent"), 1),
            "intensityType": lap.get("intensityType") or lap.get("stepType")
        }
        lap_dtos.append({k: v for k, v in lap_obj.items() if v is not None})
    return lap_dtos

def get_activities(api, target_date_str):
    """Fetch activities, calculate avg_pace, and nest their splits directly below each activity."""
    try:
        activities = api.get_activities_by_date(target_date_str, target_date_str)
    except Exception:
        activities = []

    formatted_activities = []
    for act in activities:
        act_id = act.get("activityId")
        distance_m = act.get("distance", 0) or 0
        distance_km = round(distance_m / 1000.0, 2) if distance_m else 0.0
        duration_sec = act.get("duration", 0) or 0
        duration_mins = round(duration_sec / 60.0, 2) if duration_sec else 0.0

        act_type = deep_get(act, ["activityType.typeKey", "activityType"], "")
        activity_pace = format_pace(distance_m, duration_sec, act_type)

        activity_obj = {
            "activityId": act_id,
            "name": act.get("activityName"),
            "type": act_type,
            "distance_km": distance_km,
            "duration_mins": duration_mins,
            "avg_pace": activity_pace,
            "average_hr": safe_float(act.get("averageHR") or act.get("avgHR")),
            "max_hr": safe_float(act.get("maxHR") or act.get("maximumHR")),
            "aerobic_training_effect": safe_float(act.get("aerobicTrainingEffect")),
            "anaerobic_training_effect": safe_float(act.get("anaerobicTrainingEffect"))
        }

        if act_id:
            splits = get_activity_splits(api, act_id, act_type)
            if splits:
                activity_obj["activity_splits"] = splits

        formatted_activities.append({k: v for k, v in activity_obj.items() if v is not None})
    return formatted_activities

def main():
    ph_today = datetime.now(ZoneInfo("Asia/Manila")).strftime("%Y-%m-%d")

    parser = argparse.ArgumentParser(description="Fetch Garmin data with Garmin export-aligned lap splits.")
    parser.add_argument("--date", type=str, default=ph_today, help="Date in YYYY-MM-DD format")
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
    health_metrics = get_health_metrics(api, target_date_str)
    activities = get_activities(api, target_date_str)

    payload = {
        "date": target_date_str,
        "training_history": training_history,
        "health_metrics": health_metrics,
        "activities": activities
    }

    os.makedirs("data", exist_ok=True)
    file_path = os.path.join("data", f"garmin_data_{target_date_str}.json")
    with open(file_path, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"Successfully generated Garmin JSON at: {file_path}")

if __name__ == "__main__":
    main()
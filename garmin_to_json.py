import os
import json
from datetime import datetime
from garminconnect import Garmin

def format_time(seconds):
    if not seconds or seconds == "N/A" or seconds <= 0:
        return "N/A"
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}:{s:02d}"

def speed_to_pace_metrics(speed_mps):
    if not speed_mps or speed_mps <= 0:
        return "N/A", "N/A"
    sec_per_km = 1000.0 / speed_mps
    formatted_pace = format_time(sec_per_km)
    decimal_pace = round(sec_per_km / 60.0, 2)
    return formatted_pace, decimal_pace

def get_lap_metric(lap, possible_keys, default="N/A"):
    """Safely checks multiple alternative keys for a Garmin metric."""
    for key in possible_keys:
        val = lap.get(key)
        if val is not None and val != "":
            return val
    return default

def main():
    garmin_tokens_json = os.environ.get("GARMIN_TOKENS_JSON")
    if not garmin_tokens_json:
        raise ValueError("GARMIN_TOKENS_JSON environment variable is missing.")

    token_dir = "./.garminconnect"
    os.makedirs(token_dir, exist_ok=True)
    with open(os.path.join(token_dir, "garmin_tokens.json"), "w") as f:
        f.write(garmin_tokens_json)

    api = Garmin()
    api.login(token_dir)
    today = datetime.today().strftime("%Y-%m-%d")

    # 1. FETCH HEALTH & READINESS METRICS
    stats = api.get_stats(today)
    rhr = stats.get("restingHeartRate", "N/A")
    total_steps = stats.get("totalSteps", "N/A")
    
    sleep_dto = api.get_sleep_data(today).get("dailySleepDTO", {})
    sleep_score = sleep_dto.get("sleepScores", {}).get("overall", {}).get("value", "N/A")
    sleep_duration_sec = sleep_dto.get("sleepTimeSeconds", 0)
    
    sleep_metrics = sleep_dto.get("sleepMetrics", {})
    deep_sec = sleep_dto.get("deepSleepSeconds", sleep_metrics.get("deepSleepSeconds", 0))
    light_sec = sleep_dto.get("lightSleepSeconds", sleep_metrics.get("lightSleepSeconds", 0))
    rem_sec = sleep_dto.get("remSleepSeconds", sleep_metrics.get("remSleepSeconds", 0))
    awake_sec = sleep_dto.get("awakeSleepSeconds", sleep_metrics.get("awakeSleepSeconds", 0))

    try:
        hrv_summary = api.get_hrv_data(today).get("hrvSummary", {})
        hrv_status = hrv_summary.get("status", "N/A")
        hrv_last = hrv_summary.get("lastNightAvg", "N/A")
        hrv_baseline = hrv_summary.get("baseline", "N/A")
    except Exception:
        hrv_status, hrv_last, hrv_baseline = "N/A", "N/A", "N/A"

    health_metrics = {
        "resting_hr": rhr,
        "sleep_score": sleep_score,
        "total_sleep_hours": round(sleep_duration_sec / 3600, 2),
        "sleep_stages_hours": {
            "deep": round(deep_sec / 3600, 2),
            "light": round(light_sec / 3600, 2),
            "rem": round(rem_sec / 3600, 2),
            "awake": round(awake_sec / 3600, 2)
        },
        "hrv": {
            "last_night_avg_ms": hrv_last,
            "status": hrv_status,
            "baseline_balanced_range": hrv_baseline
        },
        "total_steps": total_steps
    }

    # 2. FETCH ACTIVITIES & INTERVALS
    try:
        activities = api.get_activities_by_date(today, today)
    except Exception:
        raw_acts = api.get_activities(0, 10)
        activities = [a for a in raw_acts if a.get("startTimeLocal", "").startswith(today)]

    activities_list = []
    for act in activities:
        act_id = act.get("activityId")
        avg_speed_mps = act.get("averageSpeed", 0)
        avg_pace_str, _ = speed_to_pace_metrics(avg_speed_mps)

        summary = {
            "activity_type": act.get("activityType", {}).get("typeKey", "unknown"),
            "activity_name": act.get("activityName", "N/A"),
            "start_time": act.get("startTimeLocal", "N/A"),
            "total_distance_km": round(act.get("distance", 0) / 1000, 3),
            "total_duration_min": round(act.get("duration", 0) / 60, 2),
            "avg_pace": avg_pace_str,
            "avg_hr": act.get("averageHR", "N/A"),
            "max_hr": act.get("maxHR", "N/A"),
            "avg_cadence": get_lap_metric(act, ["averageRunningCadenceInStepsPerMinute", "averageRunCadence", "averageCadence", "runCadence", "stepsPerMinute"]),
            "avg_gct_ms": get_lap_metric(act, ["avgGroundContactTime", "averageGroundContactTime", "groundContactTime", "gct", "avgGct", "groundContactTimeInMs"]),
            "avg_stride_length_m": get_lap_metric(act, ["avgStrideLength", "averageStrideLength", "strideLength"]),
            "avg_vertical_oscillation_cm": get_lap_metric(act, ["avgVerticalOscillation", "averageVerticalOscillation", "verticalOscillation"]),
            "aerobic_te": act.get("aerobicTrainingEffect", "N/A"),
            "anaerobic_te": act.get("anaerobicTrainingEffect", "N/A"),
            "calories": act.get("calories", "N/A")
        }

        intervals = []
        if act_id:
            try:
                splits = api.get_activity_splits(act_id)
                lap_dtos = splits.get("lapDTOs", [])
                total_laps = len(lap_dtos)
                recovery_threshold = avg_speed_mps * 0.8

                for idx, lap in enumerate(lap_dtos, start=1):
                    l_dist = round(lap.get("distance", 0) / 1000, 3)
                    l_speed = lap.get("averageSpeed", 0)
                    
                    meta = f"{lap.get('intensity', '')} {lap.get('stepType', '')} {lap.get('lapType', '')}".upper()
                    
                    # Check explicit Garmin tags first before making assumptions
                    if "WARM" in meta or lap.get('stepType') == 'WARMUP':
                        step_type = "Warm Up"
                    elif any(k in meta for k in ["REST", "RECOVERY"]) or (0 < l_speed < recovery_threshold and idx > 1 and idx < total_laps and lap.get('stepType') not in ['RUN', 'INTERVAL']):
                        step_type = "Recovery"
                    elif "COOL" in meta or lap.get('stepType') == 'COOLDOWN':
                        step_type = "Cool Down"
                    else:
                        step_type = "Run"

                    l_pace, _ = speed_to_pace_metrics(l_speed)
                    intervals.append({
                        "interval_number": idx,
                        "step_type": step_type,
                        "time_min": round(lap.get("duration", 0) / 60, 2),
                        "distance_km": l_dist,
                        "avg_pace": l_pace,
                        "avg_hr": lap.get("averageHR", "N/A"),
                        "max_hr": lap.get("maxHR", "N/A"),
                        "cadence": get_lap_metric(lap, ["averageRunningCadenceInStepsPerMinute", "averageRunCadence", "averageCadence", "runCadence", "stepsPerMinute"]),
                        "avg_gct_ms": get_lap_metric(lap, ["avgGroundContactTime", "averageGroundContactTime", "groundContactTime", "gct", "avgGct", "groundContactTimeInMs"]),
                        "avg_stride_length_m": get_lap_metric(lap, ["avgStrideLength", "strideLength"]),
                        "vertical_oscillation_cm": get_lap_metric(lap, ["verticalOscillation", "avgVerticalOscillation"]),
                        "power_w": get_lap_metric(lap, ["averagePower", "avgPower", "power"])
                    })
            except Exception:
                pass

        activities_list.append({
            "summary": summary,
            "intervals": intervals
        })

    payload = {
        "date": today,
        "health_metrics": health_metrics,
        "activities": activities_list
    }

    # 3. SAVE PAYLOAD TO LOCAL JSON FILE
    os.makedirs("data", exist_ok=True)
    file_path = os.path.join("data", f"telemetry_{today}.json")
    with open(file_path, "w") as f:
        json.dump(payload, f, indent=4)
    print(f"Successfully generated telemetry JSON at: {file_path}")

if __name__ == "__main__":
    main()

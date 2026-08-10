import os
import json
import argparse
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

def get_metric(source_dict, possible_keys, default="N/A"):
    """Safely checks multiple alternative keys for a Garmin metric."""
    for key in possible_keys:
        if source_dict and key in source_dict:
            val = source_dict.get(key)
            if val is not None and val != "":
                return val
    return default

def main():
    parser = argparse.ArgumentParser(description="Fetch Garmin telemetry and health metrics for a given date.")
    parser.add_argument("--date", type=str, default=datetime.today().strftime("%Y-%m-%d"), help="Date in YYYY-MM-DD format (defaults to today)")
    args = parser.parse_args()
    target_date = args.date

    garmin_tokens_json = os.environ.get("GARMIN_TOKENS_JSON")
    if not garmin_tokens_json:
        raise ValueError("GARMIN_TOKENS_JSON environment variable is missing.")

    token_dir = "./.garminconnect"
    os.makedirs(token_dir, exist_ok=True)
    with open(os.path.join(token_dir, "garmin_tokens.json"), "w") as f:
        f.write(garmin_tokens_json)

    api = Garmin()
    api.login(token_dir)

    # 1. FETCH HEALTH & READINESS METRICS
    stats = api.get_stats(target_date)
    rhr = stats.get("restingHeartRate", "N/A")
    total_steps = stats.get("totalSteps", "N/A")
    
    sleep_dto = api.get_sleep_data(target_date).get("dailySleepDTO", {})
    sleep_score = sleep_dto.get("sleepScores", {}).get("overall", {}).get("value", "N/A")
    sleep_duration_sec = sleep_dto.get("sleepTimeSeconds", 0)
    
    sleep_metrics = sleep_dto.get("sleepMetrics", {})
    deep_sec = sleep_dto.get("deepSleepSeconds", sleep_metrics.get("deepSleepSeconds", 0))
    light_sec = sleep_dto.get("lightSleepSeconds", sleep_metrics.get("lightSleepSeconds", 0))
    rem_sec = sleep_dto.get("remSleepSeconds", sleep_metrics.get("remSleepSeconds", 0))
    awake_sec = sleep_dto.get("awakeSleepSeconds", sleep_metrics.get("awakeSleepSeconds", 0))

    # HRV & 7-Day Average Extraction
    try:
        hrv_data = api.get_hrv_data(target_date)
        hrv_summary = hrv_data.get("hrvSummary", {})
        hrv_status = hrv_summary.get("status", "N/A")
        hrv_last = hrv_summary.get("lastNightAvg", "N/A")
        hrv_baseline = hrv_summary.get("baseline", "N/A")
        hrv_weekly_avg = get_metric(hrv_summary, ["weeklyAvg", "sevenDayAvg", "sevenDayAverage"], "N/A")
    except Exception:
        hrv_status, hrv_last, hrv_baseline, hrv_weekly_avg = "N/A", "N/A", "N/A", "N/A"

    # Training Status, Acute Load, VO2 Max & Lactate Threshold Extraction
    acute_load, load_ratio, vo2_max = "N/A", "N/A", "N/A"
    lthr, lt_pace = "N/A", "N/A"

    try:
        training_status = api.get_training_status(target_date)
        if training_status:
            acute_load = get_metric(training_status, ["acuteLoad", "load", "currentAcuteLoad"], "N/A")
            load_ratio = get_metric(training_status, ["loadRatio", "acuteChronicWorkloadRatio", "loadRatioValue"], "N/A")
    except Exception:
        pass

    if acute_load == "N/A" or load_ratio == "N/A":
        try:
            user_metrics = api.get_user_summary(target_date)
            if user_metrics:
                if acute_load == "N/A":
                    acute_load = get_metric(user_metrics, ["acuteLoad", "currentAcuteLoad", "trainingLoad"], "N/A")
                if load_ratio == "N/A":
                    load_ratio = get_metric(user_metrics, ["loadRatio", "acuteChronicRatio"], "N/A")
        except Exception:
            pass

    try:
        max_metrics = api.get_max_metrics(target_date)
        if isinstance(max_metrics, list) and len(max_metrics) > 0:
            vo2_max = get_metric(max_metrics[0], ["vo2MaxValue", "vo2Max"], "N/A")
            lthr = get_metric(max_metrics[0], ["lactateThresholdHeartRate", "lthr"], "N/A")
            lt_speed = get_metric(max_metrics[0], ["lactateThresholdSpeed", "ltSpeed"], 0)
            if lt_speed and lt_speed != "N/A" and lt_speed > 0:
                lt_pace, _ = speed_to_pace_metrics(lt_speed)
        elif isinstance(max_metrics, dict):
            vo2_max = get_metric(max_metrics, ["vo2MaxValue", "vo2Max"], "N/A")
            lthr = get_metric(max_metrics, ["lactateThresholdHeartRate", "lthr"], "N/A")
            lt_speed = get_metric(max_metrics, ["lactateThresholdSpeed", "ltSpeed"], 0)
            if lt_speed and lt_speed != "N/A" and lt_speed > 0:
                lt_pace, _ = speed_to_pace_metrics(lt_speed)
    except Exception:
        pass

    health_metrics = {
        "resting_hr": rhr,
        "hrv": {
            "last_night_avg_ms": hrv_last,
            "seven_day_avg_ms": hrv_weekly_avg,
            "status": hrv_status,
            "baseline_balanced_range": hrv_baseline
        },
        "sleep_score": sleep_score,
        "total_sleep_hours": round(sleep_duration_sec / 3600, 2),
        "sleep_stages_hours": {
            "deep": round(deep_sec / 3600, 2),
            "light": round(light_sec / 3600, 2),
            "rem": round(rem_sec / 3600, 2),
            "awake": round(awake_sec / 3600, 2)
        },
        "training_status": {
            "acute_load": acute_load,
            "load_ratio": load_ratio,
            "vo2_max": vo2_max,
            "lthr": lthr,
            "lt_pace": lt_pace
        },
        "total_steps": total_steps
    }

    subjective_metrics = {
        "leg_soreness_0_10": "N/A",
        "leg_heaviness_0_10": "N/A",
        "overall_fatigue_0_10": "N/A",
        "motivation_0_10": "N/A",
        "session_rpe_0_10": "N/A"
    }

    # 2. FETCH ACTIVITIES & INTERVALS
    try:
        activities = api.get_activities_by_date(target_date, target_date)
    except Exception:
        raw_acts = api.get_activities(0, 20)
        activities = [a for a in raw_acts if a.get("startTimeLocal", "").startswith(target_date)]

    activities_list = []
    for act in activities:
        act_id = act.get("activityId")
        avg_speed_mps = act.get("averageSpeed", 0)
        avg_pace_str, _ = speed_to_pace_metrics(avg_speed_mps)

        avg_gap_mps = get_metric(act, ["averageGradeAdjustedSpeed", "gradeAdjustedSpeed"], 0)
        avg_gap_str, _ = speed_to_pace_metrics(avg_gap_mps) if avg_gap_mps != "N/A" else ("N/A", "N/A")

        summary = {
            "activity_type": act.get("activityType", {}).get("typeKey", "unknown"),
            "activity_name": act.get("activityName", "N/A"),
            "start_time": act.get("startTimeLocal", "N/A"),
            "total_distance_km": round(act.get("distance", 0) / 1000, 3),
            "total_duration_min": round(act.get("duration", 0) / 60, 2),
            "avg_pace": avg_pace_str,
            "avg_gap": avg_gap_str,
            "avg_hr": act.get("averageHR", "N/A"),
            "max_hr": act.get("maxHR", "N/A"),
            "avg_power_w": get_metric(act, ["averagePower", "avgPower"]),
            "max_power_w": get_metric(act, ["maxPower", "maximumPower"]),
            "normalized_power_w": get_metric(act, ["normalizedPower", "normPower"]),
            "avg_cadence": get_metric(act, ["averageRunningCadenceInStepsPerMinute", "averageRunCadence", "averageCadence"]),
            "avg_gct_ms": get_metric(act, ["avgGroundContactTime", "averageGroundContactTime", "groundContactTime"]),
            "avg_stride_length_m": get_metric(act, ["avgStrideLength", "averageStrideLength"]),
            "avg_vertical_oscillation_cm": get_metric(act, ["avgVerticalOscillation", "averageVerticalOscillation"]),
            "avg_vertical_ratio_pct": get_metric(act, ["avgVerticalRatio", "verticalRatio"]),
            "elevation_gain_m": get_metric(act, ["elevationGain", "totalAscent"], 0),
            "elevation_loss_m": get_metric(act, ["elevationLoss", "totalDescent"], 0),
            "avg_temperature_c": get_metric(act, ["averageTemperature", "minTemperature"]),
            "aerobic_te": act.get("aerobicTrainingEffect", "N/A"),
            "anaerobic_te": act.get("anaerobicTrainingEffect", "N/A"),
            "calories": act.get("calories", "N/A")
        }

        intervals = []
        if act_id:
            try:
                splits = api.get_activity_splits(act_id)
                lap_dtos = splits.get("lapDTOs", [])
                
                for idx, lap in enumerate(lap_dtos, start=1):
                    l_dist = round(lap.get("distance", 0) / 1000, 3)
                    l_speed = lap.get("averageSpeed", 0)
                    l_gap_speed = get_metric(lap, ["averageGradeAdjustedSpeed", "gradeAdjustedSpeed"], 0)
                    l_pace, _ = speed_to_pace_metrics(l_speed)
                    l_gap_pace, _ = speed_to_pace_metrics(l_gap_speed) if l_gap_speed != "N/A" else ("N/A", "N/A")
                    
                    meta = f"{lap.get('intensity', '')} {lap.get('stepType', '')} {lap.get('lapType', '')}".upper()
                    
                    if "WARM" in meta or lap.get('stepType') == 'WARMUP':
                        step_type = "Warm Up"
                    elif any(k in meta for k in ["REST", "RECOVERY"]):
                        step_type = "Recovery"
                    elif "COOL" in meta or lap.get('stepType') == 'COOLDOWN':
                        step_type = "Cool Down"
                    else:
                        step_type = "Run"

                    intervals.append({
                        "interval_number": idx,
                        "step_type": step_type,
                        "time_min": round(lap.get("duration", 0) / 60, 2),
                        "distance_km": l_dist,
                        "avg_pace": l_pace,
                        "avg_gap": l_gap_pace,
                        "avg_hr": lap.get("averageHR", "N/A"),
                        "max_hr": lap.get("maxHR", "N/A"),
                        "power_w": get_metric(lap, ["averagePower", "avgPower", "power"]),
                        "cadence": get_metric(lap, ["averageRunningCadenceInStepsPerMinute", "averageRunCadence", "averageCadence"]),
                        "avg_gct_ms": get_metric(lap, ["avgGroundContactTime", "averageGroundContactTime", "groundContactTime"]),
                        "avg_stride_length_m": get_metric(lap, ["avgStrideLength", "strideLength"]),
                        "vertical_oscillation_cm": get_metric(lap, ["verticalOscillation", "avgVerticalOscillation"]),
                        "vertical_ratio_pct": get_metric(lap, ["verticalRatio", "avgVerticalRatio"]),
                        "elevation_gain_m": get_metric(lap, ["elevationGain", "totalAscent"], 0),
                        "elevation_loss_m": get_metric(lap, ["elevationLoss", "totalDescent"], 0)
                    })
            except Exception:
                pass

        activities_list.append({
            "summary": summary,
            "subjective": subjective_metrics,
            "intervals": intervals
        })

    payload = {
        "date": target_date,
        "health_metrics": health_metrics,
        "activities": activities_list
    }

    # 3. SAVE PAYLOAD TO LOCAL JSON FILE (garmin_YYYY-MM-DD.json)
    os.makedirs("data", exist_ok=True)
    file_path = os.path.join("data", f"garmin_{target_date}.json")
    with open(file_path, "w") as f:
        json.dump(payload, f, indent=4)
    print(f"Successfully generated telemetry JSON for {target_date} at: {file_path}")

if __name__ == "__main__":
    main()

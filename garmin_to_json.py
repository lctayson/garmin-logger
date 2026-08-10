import os
import json
import argparse
from datetime import datetime, timedelta
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

def format_stride_length(val):
    if val is None or val == "N/A":
        return "N/A"
    try:
        # Garmin API reports stride length in centimeters; convert to meters
        return round(float(val) / 100.0, 4)
    except (ValueError, TypeError):
        return "N/A"

def deep_get(source_dict, keys, default="N/A"):
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

def main():
    parser = argparse.ArgumentParser(description="Fetch Garmin telemetry and health metrics for a given date.")
    parser.add_argument("--date", type=str, default=datetime.today().strftime("%Y-%m-%d"), help="Date in YYYY-MM-DD format (defaults to today)")
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

    # 1. FETCH HISTORICAL ACTIVITIES FOR VOLUME CALCULATIONS (Past 28 Days)
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

    training_history = {
        "7_day_distance_km": round(dist_7_days, 1),
        "28_day_avg_weekly_distance_km": avg_28_day_weekly,
        "weekly_distance_last_4_weeks_km": weekly_distances
    }

    # 2. FETCH HEALTH & READINESS METRICS FOR TARGET DATE
    stats = api.get_stats(target_date_str)
    rhr = deep_get(stats, ["restingHeartRate", "rhr"], "N/A")
    total_steps = deep_get(stats, ["totalSteps", "steps"], "N/A")
    
    sleep_data = api.get_sleep_data(target_date_str)
    sleep_dto = sleep_data.get("dailySleepDTO", {}) if isinstance(sleep_data, dict) else {}
    sleep_score = deep_get(sleep_dto, ["sleepScores.overall.value", "overallSleepScore", "sleepScore"], "N/A")
    sleep_duration_sec = deep_get(sleep_dto, ["sleepTimeSeconds", "durationInSeconds"], None)
    
    deep_sec = deep_get(sleep_dto, ["deepSleepSeconds", "sleepMetrics.deepSleepSeconds"], None)
    light_sec = deep_get(sleep_dto, ["lightSleepSeconds", "sleepMetrics.lightSleepSeconds"], None)
    rem_sec = deep_get(sleep_dto, ["remSleepSeconds", "sleepMetrics.remSleepSeconds"], None)
    awake_sec = deep_get(sleep_dto, ["awakeSleepSeconds", "sleepMetrics.awakeSleepSeconds"], None)

    hrv_status, hrv_last, hrv_baseline, hrv_weekly_avg = "N/A", "N/A", "N/A", "N/A"
    try:
        hrv_data = api.get_hrv_data(target_date_str)
        hrv_summary = hrv_data.get("hrvSummary", {}) if isinstance(hrv_data, dict) else {}
        hrv_status = deep_get(hrv_summary, ["status", "hrvStatus"], "N/A")
        hrv_last = deep_get(hrv_summary, ["lastNightAvg", "weeklyAvg", "bal"], "N/A")
        hrv_baseline = deep_get(hrv_summary, ["baseline", "baselineRange"], "N/A")
        hrv_weekly_avg = deep_get(hrv_summary, ["weeklyAvg", "sevenDayAvg", "sevenDayAverage", "lastSevenDaysAvg"], "N/A")
    except Exception:
        pass

    acute_load, load_ratio, vo2_max = "N/A", "N/A", "N/A"
    lthr, lt_pace = "N/A", "N/A"

    try:
        training_status = api.get_training_status(target_date_str)
        if training_status:
            acute_load = deep_get(training_status, ["acuteLoad", "load", "currentAcuteLoad", "trainingLoadDTO.acuteLoad"], "N/A")
            load_ratio = deep_get(training_status, ["loadRatio", "acuteChronicWorkloadRatio", "loadRatioValue"], "N/A")
    except Exception:
        pass

    try:
        max_metrics = api.get_max_metrics(target_date_str)
        if isinstance(max_metrics, list) and len(max_metrics) > 0:
            m_item = max_metrics[0]
            vo2_max = deep_get(m_item, ["vo2MaxValue", "vo2Max", "generic.vo2MaxValue"], "N/A")
            lthr = deep_get(m_item, ["lactateThresholdHeartRate", "lthr", "running.lactateThresholdHeartRate"], "N/A")
            lt_speed = deep_get(m_item, ["lactateThresholdSpeed", "ltSpeed", "running.lactateThresholdSpeed"], None)
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
        "total_sleep_hours": round(sleep_duration_sec / 3600, 2) if sleep_duration_sec else "N/A",
        "sleep_stages_hours": {
            "deep": round(deep_sec / 3600, 2) if deep_sec else "N/A",
            "light": round(light_sec / 3600, 2) if light_sec else "N/A",
            "rem": round(rem_sec / 3600, 2) if rem_sec else "N/A",
            "awake": round(awake_sec / 3600, 2) if awake_sec else "N/A"
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

    # 3. FETCH TARGET DATE ACTIVITIES & INTERVALS
    try:
        activities = api.get_activities_by_date(target_date_str, target_date_str)
    except Exception:
        activities = []

    activities_list = []
    for act in activities:
        act_id = act.get("activityId")
        avg_speed_mps = act.get("averageSpeed", None)
        avg_pace_str, _ = speed_to_pace_metrics(avg_speed_mps)

        avg_gap_mps = deep_get(act, ["averageGradeAdjustedSpeed", "gradeAdjustedSpeed"], None)
        if not avg_gap_mps or avg_gap_mps == "N/A" or avg_gap_mps <= 0:
            avg_gap_str = "N/A"
        else:
            avg_gap_str, _ = speed_to_pace_metrics(avg_gap_mps)

        raw_stride = deep_get(act, ["avgStrideLength", "averageStrideLength", "strideLength"], None)
        avg_stride_m = format_stride_length(raw_stride)

        summary = {
            "activity_type": deep_get(act, ["activityType.typeKey", "activityType"], "running"),
            "activity_name": deep_get(act, ["activityName"], "N/A"),
            "start_time": deep_get(act, ["startTimeLocal"], "N/A"),
            "total_distance_km": round(act.get("distance", 0) / 1000, 3) if act.get("distance") else "N/A",
            "total_duration_min": round(act.get("duration", 0) / 60, 2) if act.get("duration") else "N/A",
            "avg_pace": avg_pace_str,
            "avg_gap": avg_gap_str,
            "avg_hr": deep_get(act, ["averageHR", "avgHR"], "N/A"),
            "max_hr": deep_get(act, ["maxHR", "maximumHR"], "N/A"),
            "avg_power_w": deep_get(act, ["averagePower", "avgPower"], "N/A"),
            "max_power_w": deep_get(act, ["maxPower", "maximumPower"], "N/A"),
            "normalized_power_w": deep_get(act, ["normalizedPower", "normPower"], "N/A"),
            "avg_cadence": deep_get(act, ["averageRunningCadenceInStepsPerMinute", "averageRunCadence", "averageCadence"], "N/A"),
            "avg_gct_ms": deep_get(act, ["avgGroundContactTime", "averageGroundContactTime", "groundContactTime"], "N/A"),
            "avg_stride_length_m": avg_stride_m,
            "avg_vertical_oscillation_cm": deep_get(act, ["avgVerticalOscillation", "averageVerticalOscillation", "verticalOscillation"], "N/A"),
            "avg_vertical_ratio_pct": deep_get(act, ["avgVerticalRatio", "verticalRatio"], "N/A"),
            "elevation_gain_m": deep_get(act, ["elevationGain", "totalAscent"], "N/A"),
            "elevation_loss_m": deep_get(act, ["elevationLoss", "totalDescent"], "N/A"),
            "avg_temperature_c": deep_get(act, ["averageTemperature", "minTemperature", "temperature"], "N/A"),
            "aerobic_te": deep_get(act, ["aerobicTrainingEffect"], "N/A"),
            "anaerobic_te": deep_get(act, ["anaerobicTrainingEffect"], "N/A"),
            "calories": deep_get(act, ["calories"], "N/A")
        }

        intervals = []
        if act_id:
            try:
                splits = api.get_activity_splits(act_id)
                lap_dtos = splits.get("lapDTOs", [])
                for idx, lap in enumerate(lap_dtos, start=1):
                    l_dist = round(lap.get("distance", 0) / 1000, 3) if lap.get("distance") else "N/A"
                    l_speed = lap.get("averageSpeed", None)
                    l_pace, _ = speed_to_pace_metrics(l_speed)
                    
                    l_gap_speed = deep_get(lap, ["averageGradeAdjustedSpeed", "gradeAdjustedSpeed"], None)
                    if not l_gap_speed or l_gap_speed == "N/A" or l_gap_speed <= 0:
                        l_gap_pace = "N/A"
                    else:
                        l_gap_pace, _ = speed_to_pace_metrics(l_gap_speed)

                    raw_lap_stride = deep_get(lap, ["avgStrideLength", "strideLength", "averageStrideLength"], None)
                    lap_stride_m = format_stride_length(raw_lap_stride)

                    intervals.append({
                        "interval_number": idx,
                        "step_type": deep_get(lap, ["stepType"], "Run"),
                        "time_min": round(lap.get("duration", 0) / 60, 2) if lap.get("duration") else "N/A",
                        "distance_km": l_dist,
                        "avg_pace": l_pace,
                        "avg_gap": l_gap_pace,
                        "avg_hr": deep_get(lap, ["averageHR", "avgHR"], "N/A"),
                        "max_hr": deep_get(lap, ["maxHR", "maximumHR"], "N/A"),
                        "power_w": deep_get(lap, ["averagePower", "avgPower", "power"], "N/A"),
                        "cadence": deep_get(lap, ["averageRunningCadenceInStepsPerMinute", "averageRunCadence", "averageCadence"], "N/A"),
                        "avg_gct_ms": deep_get(lap, ["avgGroundContactTime", "averageGroundContactTime", "groundContactTime"], "N/A"),
                        "avg_stride_length_m": lap_stride_m,
                        "vertical_oscillation_cm": deep_get(lap, ["verticalOscillation", "avgVerticalOscillation"], "N/A"),
                        "vertical_ratio_pct": deep_get(lap, ["verticalRatio", "avgVerticalRatio"], "N/A"),
                        "elevation_gain_m": deep_get(lap, ["elevationGain", "totalAscent"], "N/A"),
                        "elevation_loss_m": deep_get(lap, ["elevationLoss", "totalDescent"], "N/A")
                    })
            except Exception:
                pass

        activities_list.append({
            "summary": summary,
            "intervals": intervals
        })

    payload = {
        "date": target_date_str,
        "training_history": training_history,
        "health_metrics": health_metrics,
        "activities": activities_list
    }

    os.makedirs("data", exist_ok=True)
    file_path = os.path.join("data", f"garmin_{target_date_str}.json")
    with open(file_path, "w") as f:
        json.dump(payload, f, indent=4)
    print(f"Successfully generated clean telemetry JSON with corrected stride lengths for {target_date_str} at: {file_path}")

if __name__ == "__main__":
    main()

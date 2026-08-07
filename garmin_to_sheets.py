import os
import json
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from garminconnect import Garmin

# --- CONFIGURATION ---
SPREADSHEET_NAME = "Garmin_Metrics_Log"

google_creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
garmin_tokens_json = os.environ.get("GARMIN_TOKENS_JSON")

if not google_creds_json:
    raise ValueError("GOOGLE_CREDENTIALS_JSON environment variable is missing.")
if not garmin_tokens_json:
    raise ValueError("GARMIN_TOKENS_JSON environment variable is missing.")

CREDENTIALS_DICT = json.loads(google_creds_json)

def ensure_worksheet_with_headers(sh, title, headers):
    """Ensures worksheet exists and has the correct header row."""
    try:
        worksheet = sh.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = sh.add_worksheet(title=title, rows="500", cols=len(headers) + 2)
    
    existing_rows = worksheet.get_all_values()
    if not existing_rows or existing_rows[0] != headers:
        worksheet.insert_row(headers, 1)
        
    return worksheet

def format_time(seconds):
    """Converts seconds into mm:ss format."""
    if not seconds or seconds == "N/A" or seconds <= 0:
        return "N/A"
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}:{s:02d}"

def speed_to_pace_metrics(speed_mps):
    """Takes speed in meters/sec and returns (formatted_mm_ss, decimal_min_per_km)."""
    if not speed_mps or speed_mps <= 0:
        return "N/A", "N/A"
    
    sec_per_km = 1000.0 / speed_mps
    formatted_pace = format_time(sec_per_km)
    decimal_pace = round(sec_per_km / 60.0, 2)
    
    return formatted_pace, decimal_pace

def get_lap_metric(lap, possible_keys, default="N/A"):
    """Safely checks multiple alternative keys for a Garmin lap metric."""
    for key in possible_keys:
        val = lap.get(key)
        if val is not None:
            return val
    return default

def main():
    print("Setting up Garmin token session...")
    token_dir = "./.garminconnect"
    os.makedirs(token_dir, exist_ok=True)
    token_file_path = os.path.join(token_dir, "garmin_tokens.json")
    
    with open(token_file_path, "w") as f:
        f.write(garmin_tokens_json)

    print("Connecting to Garmin Connect using pre-authenticated tokens...")
    api = Garmin()
    api.login(token_dir)

    today = datetime.today().strftime("%Y-%m-%d")
    print(f"Today's date is {today}. Fetching health metrics...")

    # ==========================================
    # 1. FETCH DAILY HEALTH & RECOVERY METRICS
    # ==========================================
    stats = api.get_stats(today)
    rhr = stats.get("restingHeartRate", "N/A")
    total_steps = stats.get("totalSteps", "N/A")
    
    sleep_data = api.get_sleep_data(today)
    daily_sleep = sleep_data.get("dailySleepDTO", {})
    sleep_score = daily_sleep.get("sleepScores", {}).get("overall", {}).get("value", "N/A")
    
    sleep_sec = daily_sleep.get("sleepTimeSeconds", 0)
    deep_sec = daily_sleep.get("deepSleepSeconds", 0)
    light_sec = daily_sleep.get("lightSleepSeconds", 0)
    rem_sec = daily_sleep.get("remSleepSeconds", 0)
    awake_sec = daily_sleep.get("awakeSleepSeconds", 0)

    sleep_hours = round(sleep_sec / 3600, 2) if sleep_sec else "N/A"
    deep_hours = round(deep_sec / 3600, 2) if deep_sec else "N/A"
    light_hours = round(light_sec / 3600, 2) if light_sec else "N/A"
    rem_hours = round(rem_sec / 3600, 2) if rem_sec else "N/A"
    awake_hours = round(awake_sec / 3600, 2) if awake_sec else "N/A"

    try:
        hrv_data = api.get_hrv_data(today)
        hrv_summary = hrv_data.get("hrvSummary", {})
        hrv_status = hrv_summary.get("status", "N/A")
        hrv_weekly_avg = hrv_summary.get("weeklyAvg", "N/A")
        hrv_last_night = hrv_summary.get("lastNightAvg", "N/A")
    except Exception:
        hrv_status, hrv_weekly_avg, hrv_last_night = "N/A", "N/A", "N/A"

    try:
        readiness_data = api.get_training_readiness(today)
        readiness_score = readiness_data.get("score", "N/A")
    except Exception:
        readiness_score = "N/A"

    # ==========================================
    # 2. FETCH LATEST ACTIVITY & SUMMARY METRICS
    # ==========================================
    activities = api.get_activities(0, 1)
    latest_activity = activities[0] if activities else {}
    
    act_name = latest_activity.get("activityName", "N/A")
    aerobic_te = latest_activity.get("aerobicTrainingEffect", "N/A")
    anaerobic_te = latest_activity.get("anaerobicTrainingEffect", "N/A")
    activity_id = latest_activity.get("activityId")

    start_time_local = latest_activity.get("startTimeLocal")
    act_date = start_time_local.split(" ")[0] if start_time_local else today

    dist_km = round(latest_activity.get("distance", 0) / 1000, 2)
    duration_min = round(latest_activity.get("duration", 0) / 60, 2)
    avg_speed_mps = latest_activity.get("averageSpeed", 0)
    avg_pace_str, avg_pace_dec = speed_to_pace_metrics(avg_speed_mps)

    avg_hr = latest_activity.get("averageHR", "N/A")
    max_hr = latest_activity.get("maxHR", "N/A")
    avg_power = get_lap_metric(latest_activity, ["averagePower", "avgPower", "power"])
    cadence = get_lap_metric(latest_activity, ["averageRunningCadenceInStepsPerMinute", "averageRunCadence", "averageCadence"])
    gct = get_lap_metric(latest_activity, ["avgGroundContactTime", "averageGroundContactTime", "groundContactTime"])

    summary_row = [
        act_date, act_name, dist_km, duration_min, avg_pace_str, avg_pace_dec, 
        avg_hr, max_hr, avg_power, cadence, gct, aerobic_te, anaerobic_te
    ]

    # Fetch lap splits with robust step classification
    laps_to_log = []
    if activity_id:
        try:
            splits_data = api.get_activity_splits(activity_id)
            interval_counter = 0
            total_laps = len(splits_data.get("lapDTOs", []))
            
            for idx, lap in enumerate(splits_data.get("lapDTOs", [])):
                l_dist = round(lap.get("distance", 0) / 1000, 2)
                l_dur_sec = lap.get("duration", 0)
                l_time_str = format_time(l_dur_sec)
                
                l_speed_mps = lap.get("averageSpeed", 0)
                l_pace_str, l_pace_dec = speed_to_pace_metrics(l_speed_mps)
                
                lap_index = idx + 1
                
                # Check all possible Garmin intensity/step type indicators
                intensity = str(lap.get("intensity", "")).upper()
                step_type_api = str(lap.get("stepType", "")).upper()
                lap_type = str(lap.get("lapType", "")).upper()
                combined_meta = f"{intensity} {step_type_api} {lap_type}"
                
                if lap_index == 1 and (l_dist > 0.5 or "WARM" in combined_meta):
                    step_type = "Warm Up"
                    interval_idx = "--"
                elif any(k in combined_meta for k in ["REST", "RECOVERY"]):
                    step_type = "Recovery"
                    interval_idx = interval_counter  # Keeps association with the current interval
                elif any(k in combined_meta for k in ["COOL", "COOLDOWN"]) or (lap_index >= total_laps - 1 and l_dist > 0.5 and "INTERVAL" not in combined_meta):
                    step_type = "Cool Down"
                    interval_idx = "--"
                else:
                    interval_counter += 1
                    step_type = "Run"
                    interval_idx = interval_counter

                lap_cadence = get_lap_metric(lap, ["averageRunCadence", "averageCadence", "runCadence"])
                lap_gct = get_lap_metric(lap, ["avgGroundContactTime", "averageGroundContactTime", "groundContactTime"])
                lap_stride = get_lap_metric(lap, ["avgStrideLength", "averageStrideLength", "strideLength"])
                lap_vert_osc = get_lap_metric(lap, ["avgVerticalOscillation", "averageVerticalOscillation", "verticalOscillation"])
                lap_vert_ratio = get_lap_metric(lap, ["avgVerticalRatio", "averageVerticalRatio", "verticalRatio"])
                lap_power = get_lap_metric(lap, ["avgPower", "averagePower", "power"])
                lap_max_power = get_lap_metric(lap, ["maxPower", "maximumPower"])
                lap_calories = lap.get("calories", "N/A")

                laps_to_log.append([
                    act_date, 
                    interval_idx, 
                    step_type, 
                    lap_index, 
                    l_time_str, 
                    l_dist, 
                    l_pace_str, 
                    l_pace_dec,
                    lap.get("averageHR", "N/A"), 
                    lap.get("maxHR", "N/A"),
                    lap_cadence, 
                    lap_gct, 
                    lap_stride,
                    lap_vert_osc,
                    lap_vert_ratio,
                    lap_power,
                    lap_max_power,
                    lap_calories
                ])

            total_duration_sec = latest_activity.get("duration", 0)
            total_time_str = format_time(total_duration_sec) if total_duration_sec else "N/A"
            
            summary_lap_row = [
                act_date,
                "--",
                "Summary",
                "--",
                total_time_str,
                dist_km,
                avg_pace_str,
                avg_pace_dec,
                avg_hr,
                max_hr,
                cadence,
                gct,
                get_lap_metric(latest_activity, ["avgStrideLength", "averageStrideLength"]),
                get_lap_metric(latest_activity, ["avgVerticalOscillation", "averageVerticalOscillation"]),
                get_lap_metric(latest_activity, ["avgVerticalRatio", "averageVerticalRatio"]),
                avg_power,
                get_lap_metric(latest_activity, ["maxPower", "maximumPower"]),
                latest_activity.get("calories", "N/A")
            ]
            laps_to_log.append(summary_lap_row)

        except Exception as e:
            print(f"Could not fetch laps for activity {activity_id}: {e}")

    # ==========================================
    # 3. CONNECT & WRITE TO GOOGLE SHEETS
    # ==========================================
    print("Connecting to Google Drive / Sheets...")
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(CREDENTIALS_DICT, scope)
    client = gspread.authorize(creds)
    sh = client.open(SPREADSHEET_NAME)

    # Tab 1: Daily Readiness
    readiness_headers = [
        "Date", "Readiness Score", "HRV Status", "HRV Weekly Avg", "HRV Last Night Avg", 
        "Resting HR", "Sleep Score", "Total Sleep (hrs)", "Deep Sleep (hrs)", 
        "Light Sleep (hrs)", "REM Sleep (hrs)", "Awake (hrs)", "Steps"
    ]
    readiness_sheet = ensure_worksheet_with_headers(sh, "Daily_Readiness", readiness_headers)
    readiness_sheet.append_row([
        today, readiness_score, hrv_status, hrv_weekly_avg, hrv_last_night, 
        rhr, sleep_score, sleep_hours, deep_hours, light_hours, rem_hours, awake_hours, total_steps
    ])

    # Tab 2: Workout Summary
    summary_headers = ["Date", "Activity Name", "Dist (km)", "Time (min)", "Avg Pace", "Avg Pace (dec)", "Avg HR", "Max HR", "Avg Power", "Cadence", "GCT (ms)", "Aerobic TE", "Anaerobic TE"]
    summary_sheet = ensure_worksheet_with_headers(sh, "Workout_Summary", summary_headers)
    summary_sheet.append_row(summary_row)

    # Tab 3: Workout Granularity
    lap_headers = [
        "Date", "Interval #", "Step Type", "Lap", "Time", "Dist (km)", 
        "Avg Pace", "Avg Pace (dec)", "Avg HR", "Max HR", "Cadence", "GCT (ms)", 
        "Stride (m)", "Vert Osc (cm)", "Vert Ratio (%)", "Power (W)", "Max Power (W)", "Calories"
    ]
    granularity_sheet = ensure_worksheet_with_headers(sh, "Workout_Granularity", lap_headers)
    
    if laps_to_log:
        for lap_row in laps_to_log:
            granularity_sheet.append_row(lap_row)
        print(f"Successfully logged metrics and splits with correct Recovery step classification!")
    else:
        print("Successfully logged daily health metrics and workout summary.")

if __name__ == "__main__":
    main()

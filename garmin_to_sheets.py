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
    
    # Check if the first row matches headers; if empty or different, set them
    existing_rows = worksheet.get_all_values()
    if not existing_rows or existing_rows[0] != headers:
        worksheet.insert_row(headers, 1)
        
    return worksheet

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
    sleep_seconds = daily_sleep.get("sleepTimeSeconds", 0)
    sleep_hours = round(sleep_seconds / 3600, 2) if sleep_seconds else "N/A"

    try:
        hrv_data = api.get_hrv_data(today)
        hrv_status = hrv_data.get("hrvSummary", {}).get("status", "N/A")
        hrv_weekly_avg = hrv_data.get("hrvSummary", {}).get("weeklyAvg", "N/A")
    except Exception:
        hrv_status, hrv_weekly_avg = "N/A", "N/A"

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

    # Extract true activity date
    start_time_local = latest_activity.get("startTimeLocal")
    act_date = start_time_local.split(" ")[0] if start_time_local else today

    # Summary metrics mirroring your screenshot
    dist_km = round(latest_activity.get("distance", 0) / 1000, 2)
    duration_min = round(latest_activity.get("duration", 0) / 60, 2)
    avg_pace_val = round(duration_min / dist_km, 2) if dist_km > 0 else "N/A"
    avg_hr = latest_activity.get("averageHR", "N/A")
    max_hr = latest_activity.get("maxHR", "N/A")
    avg_power = latest_activity.get("averagePower", latest_activity.get("avgPower", "N/A"))
    cadence = latest_activity.get("averageRunningCadenceInStepsPerMinute", latest_activity.get("averageCadence", "N/A"))
    gct = latest_activity.get("avgGroundContactTime", "N/A")

    summary_row = [
        act_date, act_name, dist_km, duration_min, avg_pace_val, 
        avg_hr, max_hr, avg_power, cadence, gct, aerobic_te, anaerobic_te
    ]

    # Fetch lap splits
    laps_to_log = []
    if activity_id:
        try:
            splits_data = api.get_activity_splits(activity_id)
            for idx, lap in enumerate(splits_data.get("lapDTOs", [])):
                l_dist = round(lap.get("distance", 0) / 1000, 2)
                l_dur = round(lap.get("duration", 0) / 60, 2)
                l_pace = round(l_dur / l_dist, 2) if l_dist > 0 and l_dur > 0 else "N/A"
                
                laps_to_log.append([
                    act_date, act_name, idx + 1, l_dist, l_pace, 
                    lap.get("averageHR", "N/A"), 
                    lap.get("averageRunCadence", lap.get("averageCadence", "N/A")), 
                    lap.get("avgGroundContactTime", "N/A"), 
                    lap.get("avgPower", "N/A")
                ])
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
    readiness_headers = ["Date", "Readiness Score", "HRV Status", "HRV Avg", "Sleep (hrs)", "Sleep Score", "Resting HR", "Steps"]
    readiness_sheet = ensure_worksheet_with_headers(sh, "Daily_Readiness", readiness_headers)
    readiness_sheet.append_row([
        today, readiness_score, hrv_status, hrv_weekly_avg, sleep_hours, sleep_score, rhr, total_steps
    ])

    # Tab 2: Workout Summary (High-level metadata per workout)
    summary_headers = ["Date", "Activity Name", "Dist (km)", "Time (min)", "Avg Pace", "Avg HR", "Max HR", "Avg Power", "Cadence", "GCT (ms)", "Aerobic TE", "Anaerobic TE"]
    summary_sheet = ensure_worksheet_with_headers(sh, "Workout_Summary", summary_headers)
    summary_sheet.append_row(summary_row)

    # Tab 3: Workout Granularity (Lap-by-lap splits)
    lap_headers = ["Date", "Activity Name", "Lap", "Dist (km)", "Pace (min/km)", "Avg HR", "Cadence", "GCT (ms)", "Power (W)"]
    granularity_sheet = ensure_worksheet_with_headers(sh, "Workout_Granularity", lap_headers)
    
    if laps_to_log:
        for lap_row in laps_to_log:
            granularity_sheet.append_row(lap_row)
        print(f"Successfully logged summary and {len(laps_to_log)} lap splits!")
    else:
        print("Successfully logged daily health metrics and workout summary.")

if __name__ == "__main__":
    main()

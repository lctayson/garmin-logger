# Garmin Logger

A Python-based Garmin Connect data exporter and enrichment pipeline. It retrieves health, recovery, training, and activity data from Garmin Connect and writes structured JSON snapshots for analysis, spreadsheets, dashboards, and AI-assisted endurance coaching.

## Features

- Garmin Connect API authentication via `garminconnect`
- Daily health and recovery metrics
  - Resting heart rate
  - HRV, HRV status, and baseline range
  - Sleep duration, score, and sleep stages
  - Previous-day nap detection
  - Body Battery
- Training metrics
  - Training status
  - Acute/chronic load
  - ACWR
  - VO2 max
  - Recovery time
  - Training-load focus
- Training history
  - 7-day totals
  - 28-day average weekly running distance
  - Recent weekly endurance totals
  - Sport-specific summaries
  - Multisport activity expansion
- Activity enrichment
  - Lap/interval splits
  - Pace and grade-adjusted pace (GAP)
  - Heart rate
  - Cadence
  - Ground contact time
  - Stride length
  - Vertical oscillation and ratio
  - Running power / normalized power
  - Moving time and pace
  - Activity zones
- Garmin Running Tolerance integration
- `Asia/Manila` local-time normalization
- Regression tests for export behavior

## Data source

**Garmin Connect API is the source of truth.** Activity data is not dependent on manually maintained CSV files.

Activity splits are retrieved from Garmin Connect and normalized into a consistent schema. Garmin's grade-adjusted speed (`avgGradeAdjustedSpeed`) is converted to GAP pace during enrichment.

## Output

The `data/` directory contains dated exports and current snapshots:

| File | Purpose |
|---|---|
| `data/latest_metrics.json` | Latest health, recovery, readiness, training status/load, and training-history data |
| `data/latest_activities.json` | Latest activity data with enriched details and splits |

For downstream Garmin/training analysis, these are the **canonical current files**:

```text
data/latest_metrics.json
data/latest_activities.json
```

## Project structure

```text
.
├── data/
│   ├── latest_metrics.json
│   ├── latest_activities.json
│   └── dated JSON exports...
│
├── garmin_to_json.py
├── run_garmin_to_json.py
├── garmin_helpers.py
├── garmin_activity_enrichment.py
├── activity_zones.py
├── sport_trends.py
├── split_garmin_json.py
│
├── gen_garmin_token.py
├── add_garmin_naps.py
├── add_garmin_sleep_need.py
├── garmin_single_to_json.py
├── garmin_to_json_daily.py
├── tri_to_json.py
├── garmin_to_sheets.py
│
├── tests/
└── README.md
```

## Pipeline

```text
Garmin Connect
      │
      ▼
 garmin_to_json.py
      │
      ├── health / recovery
      ├── training status & load
      ├── training history
      └── activities
             │
             ▼
 run_garmin_to_json.py
      │
      ├── activity enrichment
      ├── activity zones
      └── running tolerance
             │
             ▼
       data/*.json
             │
             ├── latest_metrics.json
             └── latest_activities.json
```

`run_garmin_to_json.py` wraps the standard exporter and adds API-based enrichment before the final JSON is written.

## Authentication

Authentication uses `garminconnect` and a local token store. Credentials are not embedded in source code.

Generate a token with:

```bash
python gen_garmin_token.py
```

Never commit Garmin passwords, authentication tokens, or token-store contents.

## Running the exporter

For the full enriched export:

```bash
python run_garmin_to_json.py
```

This adds:

1. Activity enrichment
2. Activity zones
3. Running Tolerance

The base exporter can be run directly with:

```bash
python garmin_to_json.py
```

## Running Tolerance

When supported by the installed `garminconnect` version, training history includes a `running_tolerance` object:

```json
"running_tolerance": {
  "acute_impact_load_km": 38.6,
  "weekly_tolerance_km": 67.0,
  "actual_7_day_distance_km": 38.6,
  "status": "Medium",
  "percent_of_tolerance": 57.6
}
```

Status thresholds used by the exporter:

| Percentage of tolerance | Status |
|---:|---|
| `< 50%` | Low |
| `50–74.9%` | Medium |
| `75–100%` | High |
| `> 100%` | Exceeded |

## Activity split schema

Splits are normalized into an analysis-friendly order:

```text
interval
step_type
lap
time
distance_km
avg_pace
avg_gap
avg_hr
max_hr
elevation_gain_m
elevation_loss_m
avg_run_cadence
avg_ground_contact_time_ms
avg_stride_length_m
avg_vertical_oscillation_cm
avg_vertical_ratio_pct
normalized_power_w
avg_power_w
avg_w_kg
max_power_w
max_w_kg
calories
best_pace
max_run_cadence
moving_time
avg_moving_pace
```

### Pace conventions

- Running pace is `M:SS` per kilometer.
- GAP is converted from Garmin's grade-adjusted speed into pace.
- Cycling speed is not treated as running pace.
- Swimming uses the appropriate Garmin distance convention.

### Cumulative time

Cumulative time is intentionally not required as a split field because it can be calculated from split durations. This avoids redundant data while retaining all information needed for analysis.

## Time zone

The exporter uses:

```text
Asia/Manila
```

Garmin timestamps are normalized to Philippine local time where appropriate. This is important for interpreting activities, sleep, naps, and daily readiness.

## Data quality principles

The exporter is designed for longitudinal training analysis:

- Prefer Garmin API values over guesses or manually entered values.
- Preserve Garmin activity/sport classification.
- Convert units explicitly and consistently.
- Keep daily health data separate from activity-level data.
- Avoid redundant fields that can be deterministically calculated.
- Handle missing Garmin fields gracefully.
- Keep authentication data out of generated JSON and source control.

## Testing

Tests are located in `tests/` and cover areas such as activity export behavior, historical activity lookup, and latest-activity handling.

Run the suite with:

```bash
python -m unittest discover -s tests
```

Where practical, tests should not require live Garmin authentication.

## Google Sheets

`garmin_to_sheets.py` provides a separate path for publishing Garmin data to Google Sheets. JSON remains the preferred machine-readable intermediate format.

## Downstream / AI analysis

For a coaching or AI workflow, load the current snapshots in this order:

1. `data/latest_metrics.json` — recovery, readiness, training load, history, and overall context.
2. `data/latest_activities.json` — activity and split-level execution data.

Use the activity file to evaluate workout execution (pace, HR, cadence, power, mechanics, and interval consistency). Use the metrics file to evaluate readiness and training context before recommending the next session.

## Privacy and security

Garmin exports can contain sensitive health and location-related information. Treat generated JSON as private personal data.

Do not commit:

- Garmin passwords
- Authentication tokens
- Token-store contents
- Private credentials
- Unnecessary raw personal data

Review `data/` before making the repository public.

## License

No license is currently specified. Unless a license is added, all rights remain with the repository owner.

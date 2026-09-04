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
- Analysis-friendly metrics compaction that removes redundant/legacy representations while retaining coaching-relevant information
- Configurable IANA timezone with CLI, environment-variable, and config-file support
- Regression tests for export behavior

## Data source

**Garmin Connect API is the source of truth.** Activity data is not dependent on manually maintained CSV files.

Activity splits are retrieved from Garmin Connect and normalized into a consistent schema. Garmin's grade-adjusted speed (`avgGradeAdjustedSpeed`) is converted to GAP pace during enrichment.

## Output

The `data/` directory contains dated exports and current snapshots:

| File | Purpose |
|---|---|
| `data/latest_metrics.json` | Latest compact health, recovery, readiness, training status/load, trends, and training-history data |
| `data/latest_activities.json` | Latest activity data with enriched details and splits |

For downstream Garmin/training analysis, these are the **canonical current files**:

```text
data/latest_metrics.json
data/latest_activities.json
```

`latest_metrics.json` is canonicalized in memory during the split step. The pipeline avoids a separate post-generation compaction pass, removes redundant representations, and preserves Garmin API values rather than replacing them with estimates.

## Project structure

```text
.
├── data/
│   ├── latest_metrics.json
│   ├── latest_activities.json
│   └── dated JSON exports...
│
├── config.py
├── garmin_to_json.py
├── run_garmin_to_json.py
├── compact_metrics.py
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
 add sleep need / naps
             │
             ▼
 split_garmin_json.py
      │
      └── single-pass canonical metrics + activity formatting
             │
             ▼
       data/*.json
             │
             ├── latest_metrics.json
             └── latest_activities.json
```

`run_garmin_to_json.py` is the recommended user-facing workflow because it provides the complete API-based enrichment and timezone support. `split_garmin_json.py` performs the canonical metrics transformation once, in memory, after sleep-need and nap data have been added.

## Authentication

Authentication uses `garminconnect` and a local token store. Credentials are not embedded in source code.

Generate a token with:

```bash
python gen_garmin_token.py
```

Never commit Garmin passwords, authentication tokens, or token-store contents.

## Time zone configuration

The exporter uses an **IANA timezone** for local-date calculations and for normalizing Garmin timestamps where appropriate. Examples include:

```text
Asia/Manila
America/New_York
Europe/London
Europe/Berlin
Australia/Sydney
Asia/Tokyo
UTC
```

### Easiest setup: edit `config.py`

For a normal installation, edit one line in `config.py`:

```python
TIMEZONE = "Asia/Manila"
```

Then run the exporter normally:

```bash
python run_garmin_to_json.py
```

No environment variables, YAML files, or command-line options are required.

### Configuration precedence

The effective timezone is selected in this order:

1. `--timezone` command-line option
2. `GARMIN_TIMEZONE` environment variable
3. `TIMEZONE` in `config.py`
4. `UTC` fallback if the configured value is empty

This allows the same codebase to work cleanly for local use, cron jobs, CI/CD, containers, and other automated environments.

### Command line

Override the configured timezone for a single run:

```bash
python run_garmin_to_json.py --timezone America/New_York
```

### Environment variable

Useful for cron, Docker, CI, or GitHub Actions:

```bash
GARMIN_TIMEZONE=Europe/London python run_garmin_to_json.py
```

Example cron entry:

```cron
30 1 * * * cd /path/to/garmin-logger && GARMIN_TIMEZONE=Asia/Manila /usr/bin/python3 run_garmin_to_json.py
```

The environment-variable approach avoids having to edit the repository when the deployment environment needs a different timezone.

### Important timestamp rule

Garmin API timestamps remain the source data. The configured timezone is used to interpret timestamps locally and determine local dates; it does not alter the underlying Garmin data.

For the full enriched pipeline, `run_garmin_to_json.py` applies the configured timezone to the base generator before running it.

## Running the exporter

For the full enriched export:

```bash
python run_garmin_to_json.py
```

This adds:

1. Activity enrichment
2. Activity zones
3. Running Tolerance
4. Sleep need and date-aware naps
5. Canonical metrics/activity formatting

The base exporter can be run directly with:

```bash
python garmin_to_json.py
```

The base exporter remains useful for raw generation, while `run_garmin_to_json.py` is the recommended user-facing workflow because it provides the complete enriched export and timezone override support.

## Metrics compaction

`compact_metrics.py` keeps the metrics snapshot small without making it opaque to analysis. The canonical output retains:

- Readiness score/level, HRV, resting HR, sleep score, recovery time, and readiness-factor percentages
- Sleep stages and sleep need
- Acute/chronic load, ACWR, VO2 max, training status, and load focus
- Monthly aerobic-low, aerobic-high, and anaerobic load balance with targets
- Heat/altitude acclimation when relevant
- 7-day and 28-day training history, including sport-specific volume
- Recent daily and long-range weekly trends
- Body Battery trend
- Additional generated fields such as Running Tolerance

It removes information that is duplicated or deterministically derivable, including `legacy_running_summary` and redundant daily trend window metadata. Daily and weekly trend data uses a `columns` + `data` representation so field names are stored once instead of being repeated in every row. Weekly window start/end dates and Garmin interpretation fields such as ACWR status are retained where they remain useful for analysis.

VO2 max is stored as a scalar value (`"vo2_max": 45.0`) rather than an unnecessary `{"value": 45.0}` wrapper.

The compactor preserves unknown top-level fields so future Garmin additions are not silently discarded.

To compact an existing metrics file manually:

```bash
python compact_metrics.py data/latest_metrics.json
```

The normal GitHub Actions pipeline does **not** run this as a separate post-processing step; it calls the same canonical transformation in memory during `split_garmin_json.py`.

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

## Data quality principles

The exporter is designed for longitudinal training analysis:

- Prefer Garmin API values over guesses or manually entered values.
- Preserve Garmin activity/sport classification.
- Preserve useful Garmin interpretation fields rather than silently replacing them.
- Use explicit units in field names where practical.
- Remove only duplicated or deterministically derivable representations.
- Keep current canonical files stable so downstream analysis does not need to understand every historical/raw schema.

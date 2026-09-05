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

## Quick start

There are two common ways to use this project:

1. **Local machine** — best for development, testing, and one-off exports.
2. **GitHub Actions** — best for a hands-off daily Garmin data pipeline.

For a new user, the recommended path is:

```text
Fork repo → clone fork → install Python/dependencies → configure timezone
→ generate Garmin token locally → add token JSON as GitHub secret
→ enable GitHub Actions → run the workflow manually once → verify data/
```

**You do not need to give your Garmin password to GitHub.** `gen_garmin_token.py` is run locally and produces the token store. Only the token-store JSON is placed in GitHub Secrets.

---

## 1. Create your own copy of the repository

The repository is designed so each Garmin user has their **own copy** of the data repository. Do not write your personal Garmin data into someone else's repository.

### Recommended: Fork the repository

Open the repository on GitHub and click **Fork**. This creates your own GitHub repository, for example:

```text
https://github.com/YOUR_USERNAME/garmin-logger
```

Then clone **your fork**, not the original repository:

```bash
git clone https://github.com/YOUR_USERNAME/garmin-logger.git
cd garmin-logger
```

Add the original repository as `upstream` if you want to pull future code improvements:

```bash
git remote add upstream https://github.com/lctayson/garmin-logger.git
git remote -v
```

To update your local copy later:

```bash
git fetch upstream
git checkout main
git merge upstream/main
git push origin main
```

You generally **do not need to pull/clone the original repository separately** if you fork it. Forking creates the GitHub copy; cloning downloads your fork to your computer.

### Alternative: clone without forking

If you only want to run the exporter locally and do not need GitHub Actions or your own GitHub data repository:

```bash
git clone https://github.com/lctayson/garmin-logger.git
cd garmin-logger
```

For automated Actions, however, use a fork or another repository you control because the workflow needs permission to write generated JSON back to `data/`.

---

## 2. Install Python and dependencies

The GitHub Actions workflows currently use Python 3.12 for the main Garmin JSON pipeline. Use Python 3.10+ locally.

Create a virtual environment (recommended):

### Windows

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install "garminconnect>=0.3.5" requests gspread oauth2client
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install 'garminconnect>=0.3.5' requests gspread oauth2client
```

There is currently no `requirements.txt` in the repository, so install the dependencies explicitly as shown above.

---

## 3. Configure your timezone

Edit `config.py` and set the user's local IANA timezone:

```python
TIMEZONE = "Asia/Manila"
```

Examples:

```text
Asia/Manila
America/New_York
Europe/London
Europe/Berlin
Australia/Sydney
Asia/Tokyo
UTC
```

The timezone is used for local-date calculations and interpretation. It does **not** rewrite the underlying Garmin timestamps.

Configuration precedence is:

1. `--timezone` command-line option
2. `GARMIN_TIMEZONE` environment variable
3. `TIMEZONE` in `config.py`
4. `UTC` fallback

Examples:

```bash
python run_garmin_to_json.py --timezone Asia/Manila
```

or:

```bash
GARMIN_TIMEZONE=Asia/Manila python run_garmin_to_json.py
```

For a normal personal installation, editing `config.py` is sufficient.

---

## 4. Connect the user's Garmin Connect account

The exporter authenticates directly against the user's Garmin Connect account using `garminconnect`.

### Important security rule

**Never put a Garmin email, password, MFA code, or token JSON directly into Python source code, `config.py`, GitHub Actions YAML, or a committed file.**

The authentication flow is:

```text
Garmin account
      │
      │ email + password + MFA (if requested)
      ▼
 gen_garmin_token.py   ← run this LOCALLY
      │
      ▼
 ~/.garminconnect/garmin_tokens.json
      │
      ├── local runs use this token store directly
      │
      └── GitHub Actions: copy its JSON into a GitHub Secret
```

### Generate the Garmin token locally

From the repository directory, after installing dependencies, run:

```bash
python gen_garmin_token.py
```

The script will ask for:

```text
Enter your Garmin email:
Enter your Garmin password:
Enter MFA verification code:   # only if Garmin requests MFA
```

If authentication succeeds, it saves the Garmin session token store under:

```text
~/.garminconnect/
```

The exact token-store contents are managed by `garminconnect`; do not manually edit them.

### When should `gen_garmin_token.py` be run?

Run it **once during initial setup**, locally, before the first export.

You normally do **not** run it before every Garmin export. The generated token store is reused by `garminconnect` and can be refreshed when necessary.

If the token store becomes invalid or authentication starts failing, run the generator again locally and replace the GitHub secret with the newly generated token JSON.

### Test authentication locally

After generating the token, run:

```bash
python run_garmin_to_json.py
```

If the exporter can authenticate and create/update files under `data/`, the Garmin connection is working.

For local use, the exporter looks for the token store in the normal `garminconnect` location. GitHub Actions instead reconstructs that token store from the `GARMIN_TOKENS_JSON` secret.

---

## 5. Set up GitHub Actions authentication

If you want the repository to update automatically on GitHub, add the generated token JSON to your fork as a **GitHub Actions secret**.

In your fork:

```text
Settings
  → Secrets and variables
  → Actions
  → New repository secret
```

Create this secret:

```text
Name:
GARMIN_TOKENS_JSON
```

For the value, paste the **complete contents** of the token-store JSON file generated under:

```text
~/.garminconnect/garmin_tokens.json
```

Do not commit that file to the repository.

The Actions workflow creates the token store at runtime from this secret and restricts its file permissions. The secret itself is never written to `data/`.

### GitHub repository permissions

The main JSON workflow uses:

```yaml
permissions:
  contents: write
```

because it commits generated JSON back into the repository. If Actions cannot push changes, check that Actions are enabled and that the workflow is allowed to write repository contents.

---

## 6. Run the complete pipeline manually

The recommended user-facing workflow is:

```bash
python run_garmin_to_json.py
```

For GitHub Actions, the complete pipeline is defined in:

```text
.github/workflows/garmin_to_json.yml
```

It can be started manually from:

```text
GitHub repository
→ Actions
→ Garmin to JSON Pipeline
→ Run workflow
```

You can optionally supply a target date in `YYYY-MM-DD` format.

The workflow then:

1. Checks out the repository.
2. Installs Python dependencies.
3. Determines the export date.
4. Reconstructs the Garmin token store from `GARMIN_TOKENS_JSON`.
5. Runs `run_garmin_to_json.py`.
6. Adds Garmin sleep need.
7. Adds date-aware Garmin naps.
8. Splits/compacts the daily and activity JSON.
9. Commits changed files under `data/`.
10. Pushes the generated data to `main`.

The workflow also rebases/retries if another update reaches `main` while the job is running.

---

## 7. GitHub Actions automation and cron jobs

There are currently multiple workflows, and they have different purposes.

### A. `garmin_to_json.yml` — complete enriched pipeline

File:

```text
.github/workflows/garmin_to_json.yml
```

It supports:

- `workflow_dispatch` — manual execution
- `repository_dispatch` with event type `trigger-garmin-sync` — external/API-triggered execution

It currently does **not** contain its own `schedule`/cron trigger.

If you want this complete pipeline to run automatically every day, add a schedule trigger to the workflow, for example:

```yaml
on:
  schedule:
    - cron: '20 0 * * *'
  workflow_dispatch:
    inputs:
      date:
        description: 'Date to fetch metrics for (YYYY-MM-DD)'
        required: false
        default: ''
        type: string
  repository_dispatch:
    types: [trigger-garmin-sync]
```

GitHub Actions cron uses **UTC**, not the user's local timezone. For example:

```text
20 0 * * *
```

runs at **00:20 UTC**, which is **08:20 Asia/Manila**.

A scheduled run does not guarantee that Garmin data is already available at that exact minute. If a watch sync happens later, use another scheduled time or manually rerun the workflow.

### B. `ensure_garmin_data.yml` — hourly data refresh

File:

```text
.github/workflows/ensure_garmin_data.yml
```

The current workflow runs hourly:

```cron
17 * * * *
```

It also supports manual execution and a `.github/garmin_requests/date.txt` request mechanism.

**Important:** this workflow currently runs `run_garmin_to_json.py` directly and commits refreshed `data/`. It does not run the separate sleep-need, nap, and split steps used by the complete `garmin_to_json.yml` workflow. If you need the full enriched pipeline, use `garmin_to_json.yml` or update the hourly workflow to include those additional stages.

### C. `sync.yml` — legacy Garmin-to-Sheets workflow

File:

```text
.github/workflows/sync.yml
```

This workflow is separate from the JSON pipeline. It runs daily at:

```cron
20 0 * * *
```

and uses `GARMIN_TOKENS_JSON` plus `GOOGLE_CREDENTIALS_JSON` to run `garmin_to_sheets.py`.

If you only want the JSON exporter, this workflow is not required.

---

## 8. Local cron instead of GitHub Actions

You can also run the exporter from a Linux/macOS machine with system cron.

Example:

```cron
20 0 * * * cd /path/to/garmin-logger && /path/to/garmin-logger/.venv/bin/python run_garmin_to_json.py >> /path/to/garmin-logger/garmin.log 2>&1
```

For a local cron job, the Garmin token store remains on that machine under:

```text
~/.garminconnect/
```

Set the timezone explicitly if the machine's timezone differs from the Garmin user's timezone:

```cron
20 0 * * * cd /path/to/garmin-logger && GARMIN_TIMEZONE=Asia/Manila /path/to/garmin-logger/.venv/bin/python run_garmin_to_json.py >> /path/to/garmin-logger/garmin.log 2>&1
```

Cron also uses the machine's scheduler timezone, so make sure the scheduled time is converted correctly.

---

## 9. Repository update strategy for new users

After initial setup, there are two kinds of updates:

### Update your Garmin data

The Actions workflow normally handles this automatically. Locally:

```bash
python run_garmin_to_json.py
```

### Update the exporter code from upstream

If you forked the repository:

```bash
git fetch upstream
git checkout main
git merge upstream/main
git push origin main
```

Review conflicts carefully if you have modified the same Python files or workflow files.

Your generated `data/` files are personal data. Before merging upstream changes, make sure you understand any conflicts in that directory.

---

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

---

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
├── .github/
│   ├── workflows/
│   │   ├── garmin_to_json.yml
│   │   ├── ensure_garmin_data.yml
│   │   └── sync.yml
│   └── garmin_requests/
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

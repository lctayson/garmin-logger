# Metrics & Activity Schema Reference

Field-by-field reference for `data/latest_metrics.json` and `data/latest_activities.json`
(and their dated equivalents under `data/YYYY/MM/`). Written for anyone — human or AI —
doing training analysis, so the meaning/unit/source of each field doesn't need to be
re-derived from the pipeline source each time.

Grouping principle: sections are organized by *what the data means*, not by which Garmin
API endpoint it came from. Several sections (e.g. `load` vs `vo2_max` vs `load_balance`)
share a raw Garmin source but are split here because they answer different training
questions.

## latest_metrics.json

### `date`
Local calendar date this snapshot covers (`YYYY-MM-DD`).

### `readiness`
Garmin's composite Training Readiness score and its direct inputs, snapshotted together.
- `score` (0–100), `level` (e.g. `"Low"`), `feedback` — the headline verdict
- `resting_hr`, `hrv_last_night_avg_ms`, `hrv_7_day_avg_ms`, `hrv_status`
- `sleep_hours`, `sleep_hours_including_previous_day_nap`, `sleep_score` — same underlying
  night as the fuller `sleep` section below, kept here since they're inputs to `score`
- `recovery_hours` — Garmin's estimated hours until full recovery
- `hrv_baseline` — your personal HRV reference band (`balancedLow`/`balancedUpper`/etc.)
- `factor_details` — per-factor breakdown (`sleep_score`, `recovery_time`, `acwr`, `hrv`,
  `stress_history`, ...) each with its own `percent`/`feedback`, showing what's dragging
  the composite score down

### `health`
- `steps` — daily step count. Minimal section by design; not a major analysis focus for
  a runner, kept for completeness.

### `sleep`
Full sleep architecture and Garmin's Sleep Need model (a separate feature from
`readiness`'s summary fields above).
- `deep_h` / `light_h` / `rem_h` / `awake_h` — hours per stage
- `baseline_h`, `need_h`, `next_need_h` — your typical need, tonight's computed need,
  and tomorrow's target
- `feedback`, `training_feedback`, `sleep_history_adjustment`, `hrv_adjustment`,
  `nap_adjustment` — why tonight's need differs from baseline
- `previous_day_nap` — nap duration if logged, else `null`

### `load`
Acute:Chronic Workload Ratio (ACWR) family only — training *volume* trend, not fitness
or zone balance.
- `acute_load` (~7-day), `chronic_load` (~28-day), `acwr` (ratio), `acwr_percent`,
  `acwr_status` (`"Optimal"`/etc.), `chronic_load_range` (`{min, max}` — the band Garmin
  considers sustainable)
- `training_status` — Garmin's composite label (e.g. `"Maintaining 2"`); derived from
  load progression, kept here since it's fundamentally a load-trend verdict

### `vo2_max`
Your current VO2max estimate (single number, e.g. `44.0`). Separated from `load` because
it's a fitness/capacity marker, not a training-load metric — it happens to arrive bundled
with `load`'s raw source at the Garmin API level, not because it's the same *kind* of
data. Note: Garmin rarely attaches a VO2max value to any single activity (see
`activity_vo2max` below) — this account-level trend figure is the reliable one.

### `load_balance`
Aerobic/anaerobic training distribution vs. Garmin's target ranges for you.
- `aerobic_low`, `aerobic_high`, `anaerobic` — your current values
- `aerobic_low_target` / `aerobic_high_target` / `anaerobic_target` — each a `[min, max]`
  pair; compare the actual value against its own target range directly, don't rely on
  memorized thresholds
- `load_focus` — Garmin's verdict on which zone is off-target (e.g.
  `"Anaerobic Shortage"`); lives here (not in `load`) because it's describing *this*
  section's data

### `running_tolerance`
Impact-load-vs-personal-ceiling risk gauge — a second, independent overreach signal from
`load`'s ACWR (different Garmin subsystem, bone/impact-focused rather than
cardio-load-focused).
- `acute_impact_load`, `weekly_tolerance`, `actual_7_day_distance` — all in
  `distance_unit` (`"km"` or `"mi"`, matches your Garmin account's unit setting)
- `status` — Garmin's own label (`"Medium"`/`"High"`/etc.), taken verbatim from
  `runningToleranceFeedBackPhrase` when available
- `percent_of_tolerance` — `acute_impact_load / weekly_tolerance * 100`, unit-independent

### `training_history`
Retrospective volume/duration/load tallies only — no risk-banding, nothing forward-looking.
- `7_day` — `total_endurance` (all sports combined) and `sports` (broken out per sport,
  e.g. `running`, `other`), each with `activity_count`, `distance`, `duration_hours`,
  `exercise_load`
- `28_day` — `avg_weekly_running_distance` plus `weekly_total_endurance`, a list of
  per-week breakdowns (`week_start`, `week_end`, `total_endurance`) in the same shape

### `heat_acclimation` / `altitude_acclimation`
Physiological adaptation trackers, each its own key.
- `percentage` (0–100), `trend` (e.g. `"Acclimatized"`, or `null` if not enough data —
  common for `altitude_acclimation` if you don't train at elevation)

### `trend_recent_daily` / `trend_long_range_weekly`
Columnar time series (`columns` + `data`, one row per day/week) so multi-day patterns can
be read without re-deriving them from individual daily files. Columns mirror the fields
above (`resting_hr`, `hrv_*`, `sleep_hours`, `sleep_score`, `vo2_max`, `training_status`,
`acute_load`/`chronic_load`/`acwr`/`acwr_status`, `activity_count`, `duration_hours`,
`distance`, `sport_volume` (per-sport breakdown dict), `exercise_load`).
`trend_long_range_weekly` adds `window_start`/`window_end` per row.

### `body_battery_trend`
Columnar (`columns`: `date`, `charged`, `drained`, `high`, `low`) daily body-battery
summary — separate from any single activity's `begin_stamina_pct`/`end_stamina_pct`
(see below), which is a per-session snapshot rather than a full-day trend.

### `units`
The measurement system actually used for every unit-bearing field in this file
(`distance`, `pace`, `elevation`, `stride_length`, `vertical_oscillation`, `temperature`,
`wind_speed`, `precipitation`). Always check this before comparing across dates if the
account's unit preference could have changed.

---

## latest_activities.json (`activities: [...]`)

Each entry is one activity. Only fields not self-explanatory from their name are noted.

- `activity_vo2max` — per-activity VO2max. **Almost always absent.** Garmin rarely
  attaches a fresh VO2max estimate to any single activity (steady-state, GPS-clean runs
  are the most likely candidates; interval sessions rarely qualify). Don't treat its
  absence as a bug — check the account-level `vo2_max` in `latest_metrics.json` instead.
- `performance_condition_start` / `_end` / `_avg` — real-time in-run fitness signal
  (roughly -20 to +20), summarizing Garmin's `directPerformanceCondition` stream. The
  closest real substitute for a per-activity VO2max. Running activities only.
- `begin_stamina_pct` / `end_stamina_pct` / `min_stamina_pct` / `stamina_used_pct` —
  body battery / stamina spent during this specific session (0–100 scale, `stamina_used_pct`
  is the begin-minus-end difference). Physiological cost of *this* session, distinct from
  the full-day `body_battery_trend` above.
- `impact_load` — raw total impact load for this activity (not distance-normalized —
  a 10K will naturally read higher than a 5K; compare same-distance sessions, or use
  `running_tolerance` in the metrics file for a ceiling-aware view).
- `interval_drift` — `work_reps`, `pace_ef_drift_pct`, `hr_delta_bpm`,
  `power_ef_drift_pct`, `power_delta_w`: efficiency decay across the hard reps of an
  interval session (rising HR / falling pace for the same effort = cardiac drift, often
  heat- or fatigue-driven).
- `splits` — columnar (`columns` + `data`), one row per lap. `step_type` comes from
  Garmin's own `intensityType` (`ACTIVE` vs rest/recovery), so work vs. recovery laps
  can be told apart without guessing from pace alone.
- `weather` — `temperature`, `feels_like`, `dew_point` (all in `units.temperature`'s
  unit), `humidity_pct`, `wind_speed`, `wind_direction_deg`, `condition` (e.g.
  `"Light Rain"`). `feels_like`/`dew_point` matter more than raw `temperature` for
  judging why a run felt harder than the pace/HR alone would suggest, especially in
  humid conditions.
- `hr_zones` / `power_zones` — time-in-zone breakdowns.
- `parent_activity_id` — present on multisport child legs (swim/T1/bike/T2/run),
  pointing back to the parent triathlon/brick record.

---

## Known gaps / caveats

- `activity_vo2max` being empty on most activities is expected Garmin behavior, not a
  pipeline bug (see above).
- `heat_acclimation`/`altitude_acclimation` sourced from Garmin's own acclimation model;
  `trend: null` for altitude usually just means insufficient elevation-training data,
  not missing extraction.
- Field placement here reflects a September 2026 reorganization (`vo2_max` and
  `load_focus` were moved out of `load` into more accurate homes; `running_tolerance`
  was moved out of `training_history` into its own top-level key). Historical files
  generated before that change may still have the old nesting.

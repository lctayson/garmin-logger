"""Render latest_summary.md -- the phone-readable daily check.

Reads the already-generated latest_metrics.json / latest_activities.json and
writes a short markdown digest next to them. Purely a view over existing
files: it never calls the Garmin API and never changes the JSON.

latest_activities.json is only refreshed by split_garmin_json.py when the
target day actually has a new activity, so on a rest day it correctly still
holds the most recent real run -- its own top-level "date" is older than the
metrics file's "date" in that case. This renderer checks that date rather
than assuming whatever is in the activities file happened today.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from metrics_summary import build_summary

_ARROW = {"rising": "up", "falling": "down", "flat": "flat"}
_MAIN_SET_FIELDS = (
    ("avg_hr", "bpm", 0),
    ("stride_length", "m", 2),
    ("avg_run_cadence", "spm", 0),
    ("avg_ground_contact_time", "ms", 0),
    ("avg_vertical_oscillation", "cm", 1),
    ("avg_power", "w", 0),
)


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_json(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _hours(value: Any) -> str:
    n = _num(value)
    if n is None:
        return "-"
    return f"{int(n)}h{int(round((n - int(n)) * 60)):02d}"


def _round_half_up(value: float, places: int = 0) -> float:
    """Conventional round-half-up, since Python's round() rounds exact .5
    values to even and produces off-by-one results on the frequent case of
    two equal-duration reps averaging to a boundary value."""
    q = Decimal(10) ** -places
    result = Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)
    return float(result)


def _parse_time_seconds(text: Any) -> float | None:
    if not isinstance(text, str):
        return None
    parts = text.split(":")
    try:
        parts_i = [int(p) for p in parts]
    except ValueError:
        return None
    if len(parts_i) == 2:
        return parts_i[0] * 60 + parts_i[1]
    if len(parts_i) == 3:
        return parts_i[0] * 3600 + parts_i[1] * 60 + parts_i[2]
    return None


def _format_pace(seconds_per_km: float) -> str:
    minutes = int(seconds_per_km // 60)
    seconds = int(_round_half_up(seconds_per_km - minutes * 60))
    if seconds == 60:
        minutes += 1
        seconds = 0
    return f"{minutes}:{seconds:02d}"


def _group_active_rows(active_rows: list[list[Any]], col: dict[str, int]) -> dict[Any, list[list[Any]]]:
    """Group ACTIVE splits by workout_step_index, so e.g. warm-up strides and
    the actual work reps -- both step_type ACTIVE -- separate correctly. Falls
    back to a duration threshold (reps >=60s vs shorter bursts) when the
    workout_step_index column is missing or blank on every row, since strides
    are conventionally under a minute and real reps are not."""
    step_idx_col = col.get("workout_step_index")
    if step_idx_col is not None:
        groups: dict[Any, list[list[Any]]] = {}
        for row in active_rows:
            key = row[step_idx_col] if step_idx_col < len(row) else None
            groups.setdefault(key, []).append(row)
        if len(groups) > 1:
            return groups

    time_col = col.get("time")
    if time_col is None:
        return {}
    long_reps, short_reps = [], []
    for row in active_rows:
        secs = _parse_time_seconds(row[time_col]) if time_col < len(row) else None
        (long_reps if (secs or 0) >= 60 else short_reps).append(row)
    groups = {}
    if long_reps:
        groups["long"] = long_reps
    if short_reps:
        groups["short"] = short_reps
    return groups


def _main_set_line(act: dict[str, Any]) -> str | None:
    """Summarize the main work-rep block of an interval session: total
    distance/pace plus time-weighted HR, stride length, cadence, ground
    contact time, vertical oscillation, and power. Returns None for anything
    that isn't structured as an interval workout, or where the fields needed
    aren't present."""
    splits = act.get("splits")
    if not isinstance(splits, dict):
        return None
    columns = splits.get("columns")
    rows = splits.get("data")
    if not isinstance(columns, list) or not isinstance(rows, list):
        return None
    col = {name: i for i, name in enumerate(columns)}
    if "step_type" not in col or "time" not in col or "distance" not in col:
        return None

    # Only worth summarizing separately from the overall activity stats when
    # the workout actually has interval structure (real recoveries between
    # reps) -- a plain continuous run has nothing distinct to pull out.
    has_intervals = any(
        isinstance(row, list) and col["step_type"] < len(row) and row[col["step_type"]] in ("RECOVERY", "REST")
        for row in rows
    )
    if not has_intervals:
        return None

    active_rows = [row for row in rows if isinstance(row, list) and row[col["step_type"]] == "ACTIVE"]
    if not active_rows:
        return None

    groups = _group_active_rows(active_rows, col)
    if len(groups) < 2:
        # No distinguishable secondary group (e.g. strides) to separate the
        # main reps from -- nothing to single out from the overall totals.
        return None

    def group_duration(group_rows: list[list[Any]]) -> float:
        total = 0.0
        for row in group_rows:
            secs = _parse_time_seconds(row[col["time"]]) if col["time"] < len(row) else None
            total += secs or 0
        return total

    main_rows = groups[max(groups, key=lambda k: group_duration(groups[k]))]

    total_time = 0.0
    total_distance = 0.0
    weighted_sums = {field: 0.0 for field, _, _ in _MAIN_SET_FIELDS}
    have = {field: False for field in weighted_sums}
    for row in main_rows:
        secs = _parse_time_seconds(row[col["time"]]) if col["time"] < len(row) else None
        secs = secs or 0
        dist = _num(row[col["distance"]]) if col["distance"] < len(row) else None
        total_time += secs
        total_distance += dist or 0
        for field in weighted_sums:
            field_idx = col.get(field)
            value = _num(row[field_idx]) if field_idx is not None and field_idx < len(row) else None
            if value is not None:
                weighted_sums[field] += value * secs
                have[field] = True

    if total_time <= 0 or total_distance <= 0:
        return None

    pace = total_time / total_distance
    bits = [f"{_round_half_up(total_distance, 2):.2f}k @ {_format_pace(pace)}"]
    for field, unit, places in _MAIN_SET_FIELDS:
        if not have[field]:
            continue
        value = _round_half_up(weighted_sums[field] / total_time, places)
        text = f"{value:.{places}f}" if places else f"{int(value)}"
        bits.append(f"{text}{unit}")

    return "  - MS: " + " ".join(bits)


def _flag(is_outlier: bool) -> str:
    """A single visual marker for lines worth a second look. Deliberately not
    applied to normal lines too -- silence means normal, the marker means
    look here, so it stays a useful signal instead of decoration."""
    return "⚠️ " if is_outlier else ""


def _titleize(name: str) -> str:
    return name.replace("_", " ").title()


def _day_label(date_str: Any) -> str:
    from datetime import datetime

    if not isinstance(date_str, str):
        return str(date_str)
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%a %b %d")
    except ValueError:
        return date_str


def _find_dated_activity_file(data_dir: str, date_str: str) -> str | None:
    """Locate that day's per-activity JSON under data/<year>/<month>/. The
    naming convention changed partway through this project's history: older
    files are "<date>_activities.json", newer ones are "<date>_<slugified
    activity name>.json" -- so this globs rather than assuming one pattern."""
    if not isinstance(date_str, str) or len(date_str) < 7:
        return None
    year, month = date_str[:4], date_str[5:7]
    day_dir = os.path.join(data_dir, year, month)
    candidates = [p for p in glob.glob(os.path.join(day_dir, f"{date_str}_*.json")) if not p.endswith("_metrics.json")]
    if not candidates:
        return None
    for path in candidates:
        if path.endswith("_activities.json"):
            return path
    return sorted(candidates)[0]


def _dated_activity_names(data_dir: str | None, date_str: Any) -> list[str]:
    if not data_dir:
        return []
    path = _find_dated_activity_file(data_dir, date_str)
    if not path:
        return []
    payload = _load_json(path)
    if not isinstance(payload, dict):
        return []
    activities = payload.get("activities")
    if not isinstance(activities, list):
        return []
    return [str(act["name"]) for act in activities if isinstance(act, dict) and act.get("name")]


def _this_week_lines(payload: dict[str, Any], data_dir: str | None = None) -> list[str]:
    """Per-day breakdown of the trend_recent_daily window (usually 7 days),
    so the load/volume numbers above can be traced to specific sessions
    instead of taken on faith."""
    daily = payload.get("trend_recent_daily")
    if not isinstance(daily, dict):
        return []
    columns = daily.get("columns")
    rows = daily.get("data")
    if not isinstance(columns, list) or not isinstance(rows, list) or "date" not in columns:
        return []
    col = {name: i for i, name in enumerate(columns)}

    def cell(row: list[Any], name: str) -> Any:
        i = col.get(name)
        return row[i] if i is not None and i < len(row) else None

    lines: list[str] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        date_str = cell(row, "date")
        label = _day_label(date_str)
        count = _num(cell(row, "activity_count"))
        if not count:
            lines.append(f"- {label} — rest")
            continue

        # Prefer the actual logged activity name(s); fall back to the sport
        # type when the day's dated file can't be found (e.g. data_dir not
        # available, as in tests, or the day predates per-day file logging).
        names = _dated_activity_names(data_dir, date_str)
        if names:
            title = "/".join(names)
        else:
            sport_volume = cell(row, "sport_volume")
            sports = list(sport_volume.keys()) if isinstance(sport_volume, dict) else []
            title = "/".join(sports) if sports else "activity"
        bit = f"- {label} — {title}"
        distance = _num(cell(row, "distance"))
        if distance is not None:
            bit += f", {distance}km"
        load = _num(cell(row, "exercise_load"))
        if load is not None:
            bit += f", load {load:g}"
        lines.append(bit)

    return ["## This Week", ""] + lines if lines else []


def _readiness_lines(payload: dict[str, Any], summary: dict[str, Any]) -> list[str]:
    readiness = payload.get("readiness") or {}
    s = summary.get("readiness") or {}
    lines: list[str] = []

    score = s.get("score")
    level = s.get("level")
    header = f"## Readiness: {score if score is not None else '-'}/100"
    if level:
        header += f" ({level})"
    lines.append(header)

    feedback = readiness.get("feedback")
    if feedback:
        lines.append(f"> {feedback}")
    lines.append("")

    rhr = readiness.get("resting_hr")
    if rhr is not None:
        lines.append(f"- **RHR:** {int(_num(rhr) or 0)} bpm")

    hrv = readiness.get("hrv_last_night_avg_ms")
    if hrv is not None:
        hrv7 = readiness.get("hrv_7_day_avg_ms")
        band = (summary.get("recovery_trends") or {}).get("hrv_vs_balanced_band")
        bit = f"- {_flag(band not in (None, 'within'))}**HRV:** {int(_num(hrv) or 0)}ms"
        if hrv7 is not None:
            bit += f" (7d avg: {int(_num(hrv7) or 0)}ms)"
        if band and band != "within":
            bit += f" — {band} balanced band"
        lines.append(bit)

    sleep_h = readiness.get("sleep_hours")
    if sleep_h is not None:
        sleep_score = readiness.get("sleep_score")
        score_num = _num(sleep_score)
        bit = f"- {_flag(score_num is not None and score_num < 70)}**Sleep:** {_hours(sleep_h)}"
        if sleep_score is not None:
            bit += f" (score {int(score_num or 0)})"
        lines.append(bit)

    recovery_h = readiness.get("recovery_hours")
    if recovery_h is not None:
        lines.append(f"- {_flag(_num(recovery_h) and _num(recovery_h) >= 24)}**Recovery time:** {_num(recovery_h):g}h")

    limiter = s.get("limiting_factor")
    if limiter:
        pct = s.get("limiting_factor_percent")
        bit = f"- {_flag(True)}**Limiter:** {_titleize(limiter)}"
        if pct is not None:
            bit += f" ({pct}%)"
        lines.append(bit)
        others = [n for n in (s.get("limiting_factors") or []) if n != limiter]
        if others:
            lines.append(f"- **Also soft:** {', '.join(_titleize(n) for n in others)}")

    return lines


def _load_lines(payload: dict[str, Any], summary: dict[str, Any]) -> list[str]:
    load = payload.get("load") or {}
    balance = payload.get("load_balance") or {}
    tolerance = payload.get("running_tolerance") or {}
    v = summary.get("volume") or {}
    lines: list[str] = ["## Load & Trends", ""]

    if load.get("acwr") is not None:
        acwr_status = load.get("acwr_status")
        bit = f"- {_flag(bool(acwr_status) and acwr_status != 'Optimal')}**ACWR:** {load['acwr']}"
        if acwr_status:
            bit += f" ({acwr_status})"
        acute = _num(load.get("acute_load"))
        chronic = _num(load.get("chronic_load"))
        if acute is not None and chronic is not None:
            bit += f" — acute {acute:g} / chronic {chronic:g}"
        rng = load.get("chronic_load_range")
        if isinstance(rng, dict) and rng.get("min") is not None and rng.get("max") is not None:
            bit += f" (chronic range {rng['min']:g}–{rng['max']:g})"
        lines.append(bit)

    if v.get("distance_7d_km") is not None:
        bit = f"- **7-day volume:** {v['distance_7d_km']}km"
        avg28 = v.get("avg_weekly_distance_28d_km")
        delta = v.get("distance_7d_vs_28d_avg_pct")
        if avg28 is not None:
            bit += f" vs 28-day avg {avg28}km"
            if delta is not None:
                bit += f" ({delta:+.0f}%)"
        lines.append(bit)

    if tolerance.get("percent_of_tolerance") is not None:
        pct = _num(tolerance.get("percent_of_tolerance"))
        tol_status = tolerance.get("status")
        bit = f"- {_flag(pct is not None and pct >= 85)}**Running tolerance:** {tolerance['percent_of_tolerance']}%"
        if tol_status:
            bit += f" ({tol_status})"
        actual = _num(tolerance.get("actual_7_day_distance"))
        weekly_cap = _num(tolerance.get("weekly_tolerance"))
        if actual is not None and weekly_cap is not None:
            bit += f" — {actual:g}km of {weekly_cap:g}km weekly cap"
        acute_impact = _num(tolerance.get("acute_impact_load"))
        if acute_impact is not None:
            bit += f", acute impact load {acute_impact:g}"
        lines.append(bit)

    for name, label in (("aerobic_low", "Aerobic Low"), ("aerobic_high", "Aerobic High"), ("anaerobic", "Anaerobic")):
        value = _num(balance.get(name))
        target = balance.get(f"{name}_target")
        if value is None or not isinstance(target, list) or len(target) != 2:
            continue
        lo, hi = _num(target[0]), _num(target[1])
        off_target = (lo is not None and value < lo) or (hi is not None and value > hi)
        bit = f"- {_flag(off_target)}**{label}:** {value:g} (target {lo:g}–{hi:g}"
        if lo is not None and value < lo:
            bit += f" — {value - lo:+.0f} under)"
        elif hi is not None and value > hi:
            bit += f" — {value - hi:+.0f} over)"
        else:
            bit += " — in range)"
        lines.append(bit)
    if balance.get("load_focus"):
        focus = balance["load_focus"]
        lines.append(f"- {_flag('balanced' not in str(focus).lower())}**Load focus:** {focus}")

    trends = summary.get("recovery_trends") or {}
    if trends.get("sleep_7d_avg_h") is not None:
        below = trends.get("sleep_nights_below_need")
        sleep_trend = trends.get("sleep_trend")
        bit = f"- {_flag(bool(below) and below >= 4)}**Sleep (7d avg):** {_hours(trends['sleep_7d_avg_h'])}"
        if below:
            bit += f", {below}/7 nights below need"
        if sleep_trend:
            bit += f", trending {_ARROW.get(sleep_trend, sleep_trend)}"
        lines.append(bit)
    if trends.get("resting_hr_7d_avg") is not None:
        rhr_trend = trends.get("resting_hr_trend")
        bit = f"- {_flag(rhr_trend == 'rising')}**RHR (7d avg):** {trends['resting_hr_7d_avg']}"
        if rhr_trend:
            bit += f", trending {_ARROW.get(rhr_trend, rhr_trend)}"
        lines.append(bit)
    if trends.get("hrv_trend"):
        hrv_trend = trends["hrv_trend"]
        lines.append(f"- {_flag(hrv_trend == 'falling')}**HRV:** trending {_ARROW.get(hrv_trend, hrv_trend)}")

    return lines if len(lines) > 2 else []


def _activity_detail_lines(act: dict[str, Any]) -> list[str]:
    name = act.get("name") or act.get("type") or "Activity"
    bit = f"- **{name}**"
    detail = []
    if act.get("distance") is not None:
        detail.append(f"{act['distance']}km")
    if act.get("time"):
        detail.append(str(act["time"]))
    if act.get("avg_pace"):
        detail.append(f"{act['avg_pace']}/km")
    if act.get("avg_hr") is not None:
        hr_bit = f"HR {int(_num(act['avg_hr']) or 0)}"
        if act.get("max_hr") is not None:
            hr_bit += f"/{int(_num(act['max_hr']) or 0)} max"
        detail.append(hr_bit)
    if detail:
        bit += f" — {' · '.join(detail)}"
    lines = [bit]

    te = act.get("training_effect")
    if isinstance(te, dict):
        te_bits = []
        if te.get("label"):
            te_bits.append(str(te["label"]))
        if te.get("aerobic") is not None:
            aerobic = _num(te.get("aerobic"))
            if aerobic is not None:
                te_bits.append(f"aerobic {aerobic:g}")
        if te.get("anaerobic") is not None:
            anaerobic = _num(te.get("anaerobic"))
            if anaerobic is not None:
                te_bits.append(f"anaerobic {anaerobic:g}")
        if te_bits:
            lines.append(f"  - TE: {' · '.join(te_bits)}")

    drift = act.get("interval_drift")
    if isinstance(drift, dict) and drift.get("work_reps"):
        drift_bits = [f"{drift['work_reps']} work reps"]
        if drift.get("pace_ef_drift_pct") is not None:
            drift_bits.append(f"pace drift {drift['pace_ef_drift_pct']:+}%")
        if drift.get("hr_delta_bpm") is not None:
            drift_bits.append(f"HR +{int(_num(drift['hr_delta_bpm']) or 0)}bpm")
        lines.append(f"  - Intervals: {' · '.join(drift_bits)}")

    ms_line = _main_set_line(act)
    if ms_line:
        lines.append(ms_line)
    return lines


def _today_lines(metrics_date: Any, activities_payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(activities_payload, dict):
        return ["## Today", "", "_No activity file found._"]

    activities_date = activities_payload.get("date")
    activities = activities_payload.get("activities")
    has_activities = isinstance(activities, list) and bool(activities)

    # The activities file only refreshes on a day with a real activity, so an
    # older date here means today is a rest day and this is the last logged
    # run, not today's. Label it as such rather than implying it's today's.
    is_today = metrics_date is not None and activities_date == metrics_date

    if is_today and has_activities:
        lines = ["## Today", ""]
        for act in activities:
            if isinstance(act, dict):
                lines.extend(_activity_detail_lines(act))
        return lines

    if not has_activities:
        return ["## Today — Rest Day", "", "_No activity logged._"]

    # Stale file: real activities present, but dated before today.
    lines = ["## Today — Rest Day", "", f"_Most recent activity ({activities_date}):_"]
    for act in activities:
        if isinstance(act, dict):
            lines.extend(_activity_detail_lines(act))
    return lines


def render(metrics: dict[str, Any], activities: dict[str, Any] | None, data_dir: str | None = None) -> str:
    summary = metrics.get("summary")
    if not isinstance(summary, dict):
        summary = build_summary(metrics)

    date = metrics.get("date", "")
    out: list[str] = [f"# Daily Check — {date}".rstrip(), ""]
    out.extend(_readiness_lines(metrics, summary))
    out.append("")
    out.extend(_today_lines(date, activities))
    out.append("")

    load_lines = _load_lines(metrics, summary)
    if load_lines:
        out.extend(load_lines)
        out.append("")

    week_lines = _this_week_lines(metrics, data_dir)
    if week_lines:
        out.extend(week_lines)
        out.append("")

    # Collapse repeated blank lines from optional sections being empty.
    cleaned: list[str] = []
    for line in out:
        if line == "" and cleaned and cleaned[-1] == "":
            continue
        cleaned.append(line)
    return "\n".join(cleaned).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Render latest_summary.md from the latest metrics/activities JSON.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--metrics", default=None, help="Defaults to <data-dir>/latest_metrics.json")
    parser.add_argument("--activities", default=None, help="Defaults to <data-dir>/latest_activities.json")
    parser.add_argument("--out", default=None, help="Defaults to <data-dir>/latest_summary.md")
    args = parser.parse_args()

    metrics_path = args.metrics or os.path.join(args.data_dir, "latest_metrics.json")
    activities_path = args.activities or os.path.join(args.data_dir, "latest_activities.json")
    out_path = args.out or os.path.join(args.data_dir, "latest_summary.md")

    metrics = _load_json(metrics_path)
    if metrics is None:
        raise SystemExit(f"could not read metrics file: {metrics_path}")
    activities = _load_json(activities_path)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(render(metrics, activities, args.data_dir))
    print(out_path)


if __name__ == "__main__":
    main()

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
import csv
import glob
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
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
    # Garmin can append a tiny final partial lap (e.g. 0:11 and 0.03 km)
    # to an otherwise continuous run. It is not a stride/short rep: keep it
    # with the long splits so the main-set distance matches the activity's
    # true distance instead of silently dropping the remainder.
    distance_col = col.get("distance")
    if long_reps and short_reps and active_rows[-1] is short_reps[-1]:
        final_row = short_reps[-1]
        final_secs = _parse_time_seconds(final_row[time_col]) if time_col < len(final_row) else None
        final_distance = _num(final_row[distance_col]) if distance_col is not None and distance_col < len(final_row) else None
        if (
            len(short_reps) == 1
            and final_secs is not None and final_secs < 30
            and final_distance is not None and 0 < final_distance <= 0.1
        ):
            long_reps.append(final_row)
            short_reps = []

    groups = {}
    if long_reps:
        groups["long"] = long_reps
    if short_reps:
        groups["short"] = short_reps
    return groups


def _main_set_line(act: dict[str, Any]) -> str | None:
    """Summarize the main effort of a run: total distance/pace plus
    time-weighted HR, stride length, cadence, ground contact time, vertical
    oscillation, and power. For a continuous run with no interval structure,
    that's simply the whole run's averages. When the activity has real
    interval structure (recovery-bounded reps, e.g. strides or quality
    reps), it's the largest-duration group of ACTIVE/INTERVAL splits --
    the main set, not the warm-up strides or finisher strides tacked on
    either side. Returns None only when the fields needed aren't present.
    """
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

    active_rows = [
        row for row in rows
        if isinstance(row, list) and col["step_type"] < len(row) and row[col["step_type"]] in ("ACTIVE", "INTERVAL")
    ]
    if not active_rows:
        return None

    groups = _group_active_rows(active_rows, col)
    if not groups:
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
    return "⚠️ " if is_outlier else ""


def _titleize(name: str) -> str:
    return name.replace("_", " ").title()


def _day_label_single_letter(date_str: Any) -> str:
    from datetime import datetime

    if not isinstance(date_str, str):
        return str(date_str)
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%a")[0]
    except ValueError:
        return date_str


def _week_range_label(date_strs: list[Any]) -> str | None:
    from datetime import datetime

    parsed = []
    for d in date_strs:
        if not isinstance(d, str):
            continue
        try:
            parsed.append(datetime.strptime(d, "%Y-%m-%d"))
        except ValueError:
            continue
    if not parsed:
        return None
    start, end = min(parsed), max(parsed)
    if start.year != end.year:
        return f"{start.strftime('%b')} {start.day}, {start.year} – {end.strftime('%b')} {end.day}, {end.year}"
    if start.month != end.month:
        return f"{start.strftime('%b')} {start.day} – {end.strftime('%b')} {end.day}"
    return f"{start.strftime('%b')} {start.day}–{end.day}"


def _find_dated_activity_file(data_dir: str, date_str: str) -> str | None:
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


_LOCATION_PREFIX_RE = re.compile(r"^\S+\s*-\s*")


def _strip_location_prefix(name: str) -> str:
    if not isinstance(name, str):
        return name
    stripped = _LOCATION_PREFIX_RE.sub("", name, count=1).lstrip("_").strip()
    return stripped or name


def _shorten_activity_name(name: str) -> str:
    """Smart algorithmic cleaner for training activity names:
    - Removes location prefixes (e.g. 'Malolos - ')
    - Strips leading day-of-week labels (e.g. 'Mon ', 'Friday ')
    - Normalizes repetition multipliers ('3 × 8' -> '3x8')
    - Compacts time units ('8min' -> '8m', '30sec' -> '30s')
    - Applies standard training shorthand dictionaries (Threshold -> Thr, Intervals -> Int)
    - Normalizes generic sport terms (Running -> Run, Cycling -> Ride)
    """
    if not isinstance(name, str):
        return name
    
    # 1. Strip Garmin location prefix
    cleaned = _strip_location_prefix(name)
    
    # 2. Strip leading day names dynamically
    cleaned = re.sub(r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+", "", cleaned, flags=re.IGNORECASE)
    
    # 3. Standardize multiplication layout
    cleaned = re.sub(r"\s*[×xX]\s*", "x", cleaned)
    
    # 4. Compact time indicators
    cleaned = re.sub(r"\b(\d+)\s*mins?\b", r"\1m", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(\d+)\s*secs?\b", r"\1s", cleaned, flags=re.IGNORECASE)
    
    # 5. Smart dictionary abbreviation replacements for common training and sport terms
    abbreviations = {
        r"\bRunning\b": "Run",
        r"\bCycling\b": "Ride",
        r"\bWalking\b": "Walk",
        r"\bSwimming\b": "Swim",
        r"\bTrail Running\b": "Trail Run",
        r"\bTreadmill Running\b": "Tread Run",
        r"\bVirtual Ride\b": "Virt Ride",
        r"\bThreshold\b": "Thr",
        r"\bIntervals?\b": "Int",
        r"\bRecovery\b": "Rec",
        r"\bProgression\b": "Prog",
        r"\bStability\b": "",  # Redundant with Core/Hip
    }
    for pattern, repl in abbreviations.items():
        cleaned = re.sub(pattern, repl, cleaned, flags=re.IGNORECASE)
        
    # Clean up any leftover duplicate spacing or punctuation formatting
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"\s*/\s*", "/", cleaned)
    
    return cleaned or name


def _dated_activity_seconds(data_dir: str | None, date_str: Any) -> float:
    if not data_dir:
        return 0.0
    path = _find_dated_activity_file(data_dir, date_str)
    if not path:
        return 0.0
    payload = _load_json(path)
    if not isinstance(payload, dict):
        return 0.0
    activities = payload.get("activities")
    if not isinstance(activities, list):
        return 0.0
    total = 0.0
    for act in activities:
        if isinstance(act, dict):
            seconds = _parse_time_seconds(act.get("time"))
            if seconds is not None:
                total += seconds
    return total


def _format_week_duration(total_seconds: float) -> str:
    total = int(round(total_seconds))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _format_compact_volume(distance: float | None, day_seconds: float) -> str:
    """Format distance cleanly (dropping trailing zero e.g. 6.0k -> 6k)
    plus time appended like '6k · 34:12'."""
    time_str = _format_week_duration(day_seconds) if day_seconds > 0 else ""
    
    if distance and distance > 0:
        rounded_dist = round(distance, 1)
        if rounded_dist.is_integer():
            dist_str = f"{int(rounded_dist)}k"
        else:
            dist_str = f"{rounded_dist}k"
            
        if time_str:
            return f"{dist_str} · {time_str}"
        return dist_str
    elif time_str:
        return time_str
    return "—"


def _this_week_lines(payload: dict[str, Any], data_dir: str | None = None) -> list[str]:
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

    table_rows: list[str] = []
    seen_dates: list[Any] = []
    total_sessions = 0
    total_distance = 0.0
    total_load = 0.0
    total_seconds = 0.0
    for row in rows:
        if not isinstance(row, list):
            continue
        date_str = cell(row, "date")
        seen_dates.append(date_str)
        label = _day_label_single_letter(date_str)
        count = _num(cell(row, "activity_count"))
        if not count:
            table_rows.append(f"| {label} | Rest | — | — |")
            continue

        names = _dated_activity_names(data_dir, date_str)
        if names:
            title = "/".join(_shorten_activity_name(n) for n in names)
        else:
            sport_volume = cell(row, "sport_volume")
            sports = list(sport_volume.keys()) if isinstance(sport_volume, dict) else []
            title = "/".join(sports) if sports else "activity"

        distance = _num(cell(row, "distance"))
        day_seconds = _dated_activity_seconds(data_dir, date_str)
        
        volume_cell = _format_compact_volume(distance, day_seconds)
        
        load = _num(cell(row, "exercise_load"))
        load_cell = f"{round(load)}" if load is not None else "—"
        table_rows.append(f"| {label} | {title} | {volume_cell} | {load_cell} |")

        total_sessions += int(count)
        if distance is not None:
            total_distance += distance
        if load is not None:
            total_load += load
        total_seconds += day_seconds

    if not table_rows:
        return []
    range_label = _week_range_label(seen_dates)
    title = f"## This Week ({range_label})" if range_label else "## This Week"
    
    header = [
        title, 
        "", 
        "| D | Activity | Volume | Load |", 
        "|:---:|:---|---:|---:|"
    ]
    footer = [
        "",
        "| Sessions | Distance | Time | Load |",
        "|:---:|:---:|:---:|:---:|",
        f"| {total_sessions} | {total_distance:.2f} km | {_format_week_duration(total_seconds)} | {total_load:g} |",
    ]
    return header + table_rows + footer



def _four_week_lines(payload: dict[str, Any]) -> list[str]:
    """Render the 28-day weekly endurance breakdown in a compact table."""
    history = payload.get("training_history") or {}
    rolling = history.get("28_day") or {}
    weeks = rolling.get("weekly_total_endurance")
    if not isinstance(weeks, list) or not weeks:
        return []

    def week_label(week: dict[str, Any]) -> str:
        start = week.get("week_start")
        end = week.get("week_end")
        try:
            start_date = datetime.strptime(str(start), "%Y-%m-%d").date()
            end_date = datetime.strptime(str(end), "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return str(start or "Week")
        if start_date.year != end_date.year:
            return f"{start_date.strftime('%b')} {start_date.day}–{end_date.strftime('%b')} {end_date.day}"
        if start_date.month != end_date.month:
            return f"{start_date.strftime('%b')} {start_date.day}–{end_date.strftime('%b')} {end_date.day}"
        return f"{start_date.strftime('%b')} {start_date.day}–{end_date.day}"

    avg_weekly = _num(rolling.get("avg_weekly_running_distance"))
    lines = ["## Recent 4 Weeks"]
    if avg_weekly is not None:
        lines.append(f"_Average weekly running: {avg_weekly:g} km_")
    lines.extend([
        "",
        "| Week | Running | Others | Load |",
        "|:---|---:|---:|---:|",
    ])
    for week in reversed(weeks):
        if not isinstance(week, dict):
            continue
        total = week.get("total_endurance") or {}
        sports = week.get("sports") or {}
        running = sports.get("running") or {}
        other = sports.get("other") or {}
        run_distance = _num(running.get("distance"))
        other_hours = _num(other.get("duration_hours"))
        load = _num(total.get("exercise_load"))
        run_cell = f"{run_distance:.2f} km" if run_distance is not None else "—"
        other_cell = f"{round(other_hours * 60)} min" if other_hours is not None else "—"
        load_cell = f"{load:g}" if load is not None else "—"
        lines.append(f"| {week_label(week)} | {run_cell} | {other_cell} | {load_cell} |")
    return lines if len(lines) > (3 if avg_weekly is not None else 2) else []


def _readiness_lines(payload: dict[str, Any], summary: dict[str, Any]) -> list[str]:
    readiness = payload.get("readiness") or {}
    sleep_data = payload.get("sleep") or {}
    s = summary.get("readiness") or {}
    trends = summary.get("recovery_trends") or {}
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

    rhr = _num(readiness.get("resting_hr"))
    if rhr is not None:
        rhr7 = _num(trends.get("resting_hr_7d_avg"))
        rhr_trend = trends.get("resting_hr_trend")
        bit = f"- **RHR:** {rhr:g} bpm"
        details = []
        if rhr7 is not None:
            details.append(f"7d avg: {rhr7:g} bpm")
        if rhr_trend:
            details.append(f"trending {_ARROW.get(rhr_trend, rhr_trend)}")
        if details:
            bit += " (" + ", ".join(details) + ")"
        rhr_range = readiness.get("resting_hr_range") or readiness.get("rhr_range")
        if isinstance(rhr_range, (list, tuple)) and len(rhr_range) == 2:
            low, high = _num(rhr_range[0]), _num(rhr_range[1])
        elif isinstance(rhr_range, dict):
            low = _num(rhr_range.get("low", rhr_range.get("min")))
            high = _num(rhr_range.get("high", rhr_range.get("max")))
        else:
            low = high = None
        if low is not None and high is not None:
            status = "within" if low <= rhr <= high else ("below" if rhr < low else "above")
            bit += f" · {status} {low:g}–{high:g} bpm"
        if rhr_trend == "rising":
            bit = bit.replace("- **RHR:**", f"- {_flag(True)}**RHR:**", 1)
        lines.append(bit)

    hrv = _num(readiness.get("hrv_last_night_avg_ms"))
    if hrv is not None:
        hrv7 = _num(readiness.get("hrv_7_day_avg_ms"))
        baseline = readiness.get("hrv_baseline") or {}
        balanced_low = _num(baseline.get("balancedLow", baseline.get("balanced_low")))
        balanced_high = _num(baseline.get("balancedUpper", baseline.get("balanced_upper")))
        band = trends.get("hrv_vs_balanced_band")
        if band in (None, "within") and balanced_low is not None and balanced_high is not None:
            band = "below" if hrv < balanced_low else ("above" if hrv > balanced_high else "within")
        bit = f"- {_flag(band not in (None, 'within'))}**HRV:** {hrv:g}ms"
        if hrv7 is not None:
            bit += f" (7d avg: {hrv7:g}ms)"
        if balanced_low is not None and balanced_high is not None:
            status = "within" if balanced_low <= hrv <= balanced_high else ("below" if hrv < balanced_low else "above")
            bit += f" · {status} {balanced_low:g}–{balanced_high:g}ms"
        lines.append(bit)

    sleep_h = _num(readiness.get("sleep_hours"))
    if sleep_h is not None:
        sleep_score = _num(readiness.get("sleep_score"))
        need_h = _num(sleep_data.get("need_h"))
        if need_h is None:
            need_h = _num(trends.get("sleep_need_h"))
        bit = f"- {_flag((sleep_score is not None and sleep_score < 70) or (need_h is not None and sleep_h < need_h))}**Sleep:** {_hours(sleep_h)}"
        if need_h is not None:
            delta = sleep_h - need_h
            if abs(delta) < 0.005:
                bit += f" / {_hours(need_h)} need (met)"
            elif delta < 0:
                bit += f" / {_hours(need_h)} need ({_hours(abs(delta))} short)"
            else:
                bit += f" / {_hours(need_h)} need ({_hours(delta)} over)"
        if sleep_score is not None:
            bit += f" · score {int(sleep_score)}"
        sleep_avg = _num(trends.get("sleep_7d_avg_h"))
        below = _num(trends.get("sleep_nights_below_need"))
        if sleep_avg is not None:
            bit += f" · 7d avg {_hours(sleep_avg)}"
        if below is not None:
            bit += f" · {int(below)}/7 nights below need"
        lines.append(bit)

    recovery_h = _num(readiness.get("recovery_hours"))
    if recovery_h is not None:
        recovery_text = _hours(recovery_h) if recovery_h < 24 else f"{int(recovery_h // 24)}d {_hours(recovery_h % 24)}"
        lines.append(f"- {_flag(recovery_h >= 24)}**Recovery remaining:** {recovery_text}")

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


def _activity_detail_lines(act: dict[str, Any], readiness_line: str | None = None) -> list[str]:
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
            # Preserve the primary-benefit meaning in Garmin Connect wording.
            primary_benefit = {
                "LACTATE_THRESHOLD": "Threshold (High Aerobic)",
                "TEMPO": "Tempo (High Aerobic)",
                "VO2MAX": "VO2 Max (High Aerobic)",
                "ANAEROBIC_CAPACITY": "Anaerobic Capacity",
                "SPRINT": "Sprint (Anaerobic)",
                "BASE": "Base (Low Aerobic)",
                "RECOVERY": "Recovery (Low Aerobic)",
                "RECOVERY_RUN": "Recovery (Low Aerobic)",
                "LONG_SLOW_DISTANCE": "Base (Low Aerobic)",
            }.get(str(te["label"]).upper(), str(te["label"]).replace("_", " ").title())
            te_bits.append(primary_benefit)
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

    if readiness_line:
        lines.append(f"  - {readiness_line}")

    ai_analysis = act.get("ai_analysis")
    if ai_analysis:
        lines.append(f"  - 🧠 {ai_analysis}")
    return lines


def _post_workout_readiness_line(
    metrics_payload: dict[str, Any] | None, activity_date: Any
) -> str | None:
    """Format pre- to post-workout readiness and remaining recovery on one line."""
    if not isinstance(metrics_payload, dict) or metrics_payload.get("date") != activity_date:
        return None
    readiness = metrics_payload.get("readiness")
    snapshots = readiness.get("snapshots") if isinstance(readiness, dict) else None
    if not isinstance(snapshots, list):
        return None

    before = next(
        (item for item in snapshots
         if isinstance(item, dict) and item.get("context") == "AFTER_WAKEUP_RESET"),
        None,
    )
    after = next(
        (item for item in reversed(snapshots)
         if isinstance(item, dict) and item.get("context") == "AFTER_POST_EXERCISE_RESET"),
        None,
    )
    if not after:
        return None

    parts = []
    before_score = _num(before.get("score")) if before else None
    after_score = _num(after.get("score"))
    if before_score is not None and after_score is not None:
        parts.append(f"Readiness {before_score:g} → {after_score:g}")
    elif after_score is not None:
        parts.append(f"Readiness {after_score:g}")

    feedback = after.get("feedback")
    if feedback:
        feedback_text = str(feedback).replace("_", " ").title()
        if parts:
            parts[-1] += f" ({feedback_text})"
        else:
            parts.append(f"Readiness ({feedback_text})")

    recovery_minutes = _num(after.get("recovery_minutes"))
    if recovery_minutes is not None:
        recovery_minutes = max(0, int(round(recovery_minutes)))
        hours, minutes = divmod(recovery_minutes, 60)
        if hours >= 24:
            days, hours = divmod(hours, 24)
            recovery_text = f"{days}d {hours}h {minutes}m" if minutes else f"{days}d {hours}h"
        else:
            recovery_text = f"{hours}h {minutes}m" if minutes else f"{hours}h"
        parts.append(f"Recovery {recovery_text}")
    return " · ".join(parts) if parts else None


def _today_lines(
    metrics_date: Any,
    activities_payload: dict[str, Any] | None,
    metrics_payload: dict[str, Any] | None = None,
) -> list[str]:
    if not isinstance(activities_payload, dict):
        return ["## Activity", "", "_No activity file found._"]

    activities_date = activities_payload.get("date")
    activities = activities_payload.get("activities")
    has_activities = isinstance(activities, list) and bool(activities)

    is_today = metrics_date is not None and activities_date == metrics_date

    if is_today and has_activities:
        lines = ["## Today's Workout", ""]
        readiness_line = _post_workout_readiness_line(metrics_payload, activities_date)
        for index, act in enumerate(activities):
            if isinstance(act, dict):
                lines.extend(_activity_detail_lines(act, readiness_line if index == 0 else None))
        return lines

    if not has_activities:
        return ["## No Activity Logged Today", "", "_No activity logged._"]

    lines = ["## Latest Activity", "", f"_Most recent activity ({activities_date}):_"]
    for act in activities:
        if isinstance(act, dict):
            lines.extend(_activity_detail_lines(act))
    return lines



TRAINING_PLAN_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vTv8AJfthvUUbO3w8H5H8cBQ2Mq0t1-huuJnE-wo9vZVYYRJ-9s14pLUw9NQlGidPqOeIeDubRdCWaH/"
    "pubhtml?gid=810767784&single=true"
)


def _published_sheet_csv_url(sheet_url: str) -> str:
    parsed = urllib.parse.urlparse(sheet_url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    query["output"] = "csv"
    query.pop("single", None)
    if parsed.path.endswith("/pubhtml"):
        path = parsed.path[:-len("/pubhtml")] + "/pub"
    elif parsed.path.endswith("/pub"):
        path = parsed.path
    else:
        raise ValueError("Expected a published Google Sheets URL")
    return urllib.parse.urlunparse(parsed._replace(path=path, query=urllib.parse.urlencode(query)))


def _fetch_training_plan_rows(sheet_url: str = TRAINING_PLAN_URL) -> list[list[str]]:
    request = urllib.request.Request(
        _published_sheet_csv_url(sheet_url),
        headers={"User-Agent": "garmin-logger-training-plan/1.0"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read().decode("utf-8-sig")
    return list(csv.reader(io.StringIO(raw)))


def _parse_week_start(value: str, target_year: int):
    from datetime import date

    value = value.strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    for fmt in ("%b %d", "%B %d", "%d %b", "%d %B", "%m/%d"):
        try:
            month_day = datetime.strptime(value, fmt)
        except ValueError:
            continue
        candidates = []
        for year in (target_year - 1, target_year, target_year + 1):
            try:
                candidates.append(date(year, month_day.month, month_day.day))
            except ValueError:
                continue
        matching = [
            candidate for candidate in candidates
            if candidate <= date(target_year, month_day.month, month_day.day)
            and date(target_year, month_day.month, month_day.day) <= candidate + timedelta(days=6)
        ]
        if matching:
            return matching[0]
        if candidates:
            return min(candidates, key=lambda candidate: abs((candidate - date(target_year, month_day.month, month_day.day)).days))
    return None


def _flag_is_current(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "x", "current", "active", "✓", "☑"}


def _planned_session_from_sheet(next_day: Any, sheet_url: str) -> str | None:
    """Read the live plan: column B is week start, C:I are Mon-Sun, M flags current week."""
    from datetime import date, timedelta

    rows = _fetch_training_plan_rows(sheet_url)
    if not rows:
        return None

    # Find a row containing recognizable weekday headings, if present.
    weekday_names = {"mon": 0, "monday": 0, "tue": 1, "tues": 1, "tuesday": 1,
                     "wed": 2, "wednesday": 2, "thu": 3, "thur": 3, "thurs": 3,
                     "thursday": 3, "fri": 4, "friday": 4, "sat": 5, "saturday": 5,
                     "sun": 6, "sunday": 6}
    day_columns = None
    for row in rows[:12]:
        found = {}
        for index, cell in enumerate(row):
            normalized = re.sub(r"[^a-z]", "", cell.strip().lower())
            if normalized in weekday_names:
                found[weekday_names[normalized]] = index
        if len(found) >= 5:
            day_columns = found
            break
    if day_columns is None:
        day_columns = {day: day + 2 for day in range(7)}  # C:I, Monday-Sunday

    candidates = []
    for row in rows:
        if len(row) < 2:
            continue
        week_start = _parse_week_start(row[1], next_day.year)
        if week_start and week_start <= next_day <= week_start + timedelta(days=6):
            flag = row[12] if len(row) > 12 else ""
            candidates.append((week_start, _flag_is_current(flag), row))

    if not candidates:
        return None
    # Prefer the row explicitly flagged in hidden column M when dates overlap.
    _, _, selected = max(candidates, key=lambda item: (item[1], item[0]))
    weekday_index = next_day.weekday()
    column = day_columns.get(weekday_index)
    if column is None or column >= len(selected):
        return None
    prescription = selected[column].strip()
    return prescription or None


def _planned_session(context_text: str, next_day: Any, plan_heading: str) -> str | None:
    """Find a dated prescription in Markdown first, then fall back to the live sheet."""
    from datetime import date, timedelta

    lines = context_text.splitlines()
    try:
        heading_index = lines.index(plan_heading)
    except ValueError:
        return None

    section_lines = []
    for line in lines[heading_index + 1:]:
        if line.startswith("# ") and not line.startswith("## "):
            break
        section_lines.append(line)

    week_pattern = re.compile(r"^## W\d+\s*[·|]\s*([A-Za-z]{3})\s+(\d{1,2})\b")
    day_pattern = re.compile(r"^- \*\*(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\*\*\s+(.+)$")
    for i, line in enumerate(section_lines):
        match = week_pattern.match(line)
        if not match:
            continue
        month_text, day_text = match.groups()
        week_start = None
        for year in (next_day.year - 1, next_day.year, next_day.year + 1):
            try:
                candidate = date(year, datetime.strptime(month_text, "%b").month, int(day_text))
            except ValueError:
                continue
            if candidate <= next_day <= candidate + timedelta(days=6):
                week_start = candidate
                break
        if week_start is None:
            continue
        for day_line in section_lines[i + 1:]:
            if day_line.startswith("## W"):
                break
            day_match = day_pattern.match(day_line)
            if day_match and day_match.group(1).lower() == next_day.strftime("%a").lower():
                return day_match.group(2).strip()

    sheet_match = re.search(r"https://docs\.google\.com/spreadsheets/d/e/[^\s)]+", "\n".join(section_lines))
    sheet_url = sheet_match.group(0).rstrip("]>,.") if sheet_match else TRAINING_PLAN_URL
    try:
        return _planned_session_from_sheet(next_day, sheet_url)
    except Exception as exc:
        print(f"[render_summary_md] Could not read live training plan: {exc}", file=sys.stderr)
        return None


def _session_guidance_lines(metrics: dict[str, Any], data_dir: str | None = None, *, day_offset: int = 1) -> list[str]:
    """Give conservative guidance for today's or tomorrow's planned session."""
    from datetime import date, timedelta
    from pathlib import Path
    from config import resolve_training_plan_heading

    try:
        today = date.fromisoformat(str(metrics.get("date", "")))
    except ValueError:
        return []
    target_day = today + timedelta(days=day_offset)
    context_path = Path(__file__).with_name("training_context.md")
    try:
        context_text = context_path.read_text(encoding="utf-8")
    except OSError:
        return []
    session = _planned_session(context_text, target_day, resolve_training_plan_heading())
    if not session:
        return []

    lowered_session = session.lower()
    quality = (
        any(word in lowered_session for word in
            ("threshold", "vo2", "interval", "tempo", "time trial", "test", "race"))
        or bool(re.search(r"\b\d+\s*[x×]\s*\d+", lowered_session))
    )
    readiness = metrics.get("readiness") or {}
    summary = metrics.get("summary")
    if not isinstance(summary, dict):
        summary = build_summary(metrics)
    trends = summary.get("recovery_trends") or {}
    load = metrics.get("load") or {}
    tolerance = metrics.get("running_tolerance") or {}

    score = _num(readiness.get("score"))
    if score is None:
        score = _num((summary.get("readiness") or {}).get("score"))
    sleep = _num(readiness.get("sleep_hours"))
    recovery = _num(readiness.get("recovery_hours"))
    sleep_avg = _num(trends.get("sleep_7d_avg_h"))
    short_nights = _num(trends.get("sleep_nights_below_need"))
    rhr_trend = trends.get("resting_hr_trend")
    hrv_trend = trends.get("hrv_trend")
    hrv_band = trends.get("hrv_vs_balanced_band")
    acwr_status = str(load.get("acwr_status") or "").lower()
    tolerance_pct = _num(tolerance.get("percent_of_tolerance"))

    severe: list[str] = []
    caution: list[str] = []

    # Severe signals are individually meaningful; multiple severe signals
    # are required before recommending replacing a quality session outright.
    if score is not None and score <= 25:
        severe.append(f"very low readiness ({score:g}/100)")
    elif score is not None and score <= 40:
        caution.append(f"low readiness ({score:g}/100)")

    if sleep is not None and sleep < 5:
        severe.append(f"very short sleep last night ({sleep:.1f}h)")
    elif sleep is not None and sleep < 6:
        caution.append(f"short sleep last night ({sleep:.1f}h)")

    if recovery is not None and recovery >= 36:
        severe.append(f"high remaining recovery time ({recovery:g}h)")
    elif recovery is not None and recovery >= 24:
        caution.append(f"elevated remaining recovery time ({recovery:g}h)")

    if acwr_status in {"high", "very high", "overreaching"}:
        severe.append(f"training-load status is {acwr_status}")
    if tolerance_pct is not None and tolerance_pct >= 95:
        severe.append(f"running tolerance is nearly full ({tolerance_pct:g}%)")
    elif tolerance_pct is not None and tolerance_pct >= 85:
        caution.append(f"running tolerance is high ({tolerance_pct:g}%)")

    # Chronic sleep restriction matters even after one good night. Use both
    # the 7-day mean and repeated short nights, but avoid counting the same
    # sleep pattern as several independent severe warnings.
    chronic_sleep_warning = (
        (sleep_avg is not None and sleep_avg < 6.0)
        or (short_nights is not None and short_nights >= 6)
    )
    if chronic_sleep_warning:
        caution.append(
            "ongoing sleep debt"
            + (f" (7-day average {sleep_avg:.1f}h)" if sleep_avg is not None else "")
            + (f", {int(short_nights)}/7 nights below need" if short_nights is not None else "")
        )
    elif sleep_avg is not None and sleep_avg < 6.5:
        caution.append(f"low 7-day sleep average ({sleep_avg:.1f}h)")

    if rhr_trend == "rising":
        caution.append("resting heart rate is trending up")
    if hrv_trend == "falling":
        caution.append("HRV is trending down")
    if hrv_band == "below":
        caution.append("last-night HRV is below the balanced band")

    # Two adverse autonomic trends together are more persuasive than either
    # alone. Treat them as one combined signal rather than double-counting.
    autonomic_pair = rhr_trend == "rising" and (
        hrv_trend == "falling" or hrv_band == "below"
    )
    if autonomic_pair:
        caution.append("RHR-up/HRV-down recovery pattern")

    # Deduplicate messages while preserving order; the paired signal is a
    # useful combined flag, but the individual values remain informative.
    severe = list(dict.fromkeys(severe))
    caution = list(dict.fromkeys(caution))

    if quality and len(severe) >= 2:
        decision = "Prioritize recovery"
        action = (
            "Replace the quality session with rest or a short, very easy run. "
            "Do not make up the missed intensity; reassess at the next session."
        )
    elif quality and (
        len(severe) >= 1
        or len(caution) >= 2
        or autonomic_pair
    ):
        decision = "Adjust the workout"
        action = (
            "Make this an easy aerobic run or substantially reduce the quality "
            "repetitions; keep effort controlled and stop if the warm-up feels "
            "abnormally hard. Resume the plan only if you feel normal."
        )
    elif not quality and len(severe) >= 2:
        decision = "Prioritize recovery"
        action = "Rest, or do only a short, very easy session if you feel well."
    elif not quality and (len(severe) >= 1 or len(caution) >= 3):
        decision = "Keep it easy"
        action = "Avoid adding intensity or volume; shorten the session if effort is unusually high."
    else:
        decision = "Proceed as planned"
        action = "Follow the planned session, using normal effort-based adjustments and reassess during the warm-up."

    reasons = severe + caution
    heading = "Today's Session" if day_offset == 0 else "Next Session"
    lines = [
        f"## {heading}",
        f"- **Planned:** {target_day.strftime('%a, %b %d').replace(' 0', ' ')} — {session}",
        f"- **Recommendation:** {decision}",
    ]
    if reasons:
        lines.append("- **Reason:** " + "; ".join(reasons) + ".")
    else:
        lines.append("- **Reason:** Available readiness, recovery-trend, and load indicators do not show a combination of major warnings.")
    lines.append(f"- **Action:** {action}")
    if day_offset == 0:
        ai_guidance = (readiness.get("ai_analysis") or "").strip()
        if ai_guidance:
            lines.append("")
            lines.append("### 🧠 AI Coaching Guidance")
            lines.append("")
            lines.append(ai_guidance)
    lines.append("")
    lines.append("- *Automated guidance uses available metrics only; pain, illness, unusual symptoms, or a major subjective fatigue change should override it.*")
    return lines

def render(metrics: dict[str, Any], activities: dict[str, Any] | None, data_dir: str | None = None) -> str:
    summary = metrics.get("summary")
    if not isinstance(summary, dict):
        summary = build_summary(metrics)

    date = metrics.get("date", "")
    out: list[str] = [f"# Daily Check — {date}".rstrip(), ""]
    out.extend(_readiness_lines(metrics, summary))
    out.append("")

    # Before today's workout is logged, show today's prescription first.
    # Once an activity is logged today, show its details followed by tomorrow's plan.
    activities_date = activities.get("date") if isinstance(activities, dict) else None
    activity_list = activities.get("activities") if isinstance(activities, dict) else None
    has_activity_today = (
        date is not None
        and activities_date == date
        and isinstance(activity_list, list)
        and bool(activity_list)
    )

    if has_activity_today:
        out.extend(_today_lines(date, activities, metrics))
        out.append("")
        out.extend(_session_guidance_lines(metrics, data_dir, day_offset=1))
        out.append("")
    else:
        out.extend(_session_guidance_lines(metrics, data_dir, day_offset=0))
        out.append("")
        out.extend(_today_lines(date, activities, metrics))
        out.append("")

    load_lines = _load_lines(metrics, summary)
    if load_lines:
        out.extend(load_lines)
        out.append("")

    week_lines = _this_week_lines(metrics, data_dir)
    if week_lines:
        out.extend(week_lines)
        out.append("")

    four_week_lines = _four_week_lines(metrics)
    if four_week_lines:
        out.extend(four_week_lines)
        out.append("")

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
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
import json
import os
from typing import Any

from metrics_summary import build_summary

_ARROW = {"rising": "up", "falling": "down", "flat": "flat"}


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


def _titleize(name: str) -> str:
    return name.replace("_", " ").title()


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
        bit = f"- **HRV:** {int(_num(hrv) or 0)}ms"
        if hrv7 is not None:
            bit += f" (7d avg: {int(_num(hrv7) or 0)}ms)"
        band = (summary.get("recovery_trends") or {}).get("hrv_vs_balanced_band")
        if band and band != "within":
            bit += f" — {band} balanced band"
        lines.append(bit)

    sleep_h = readiness.get("sleep_hours")
    if sleep_h is not None:
        sleep_score = readiness.get("sleep_score")
        bit = f"- **Sleep:** {_hours(sleep_h)}"
        if sleep_score is not None:
            bit += f" (score {int(_num(sleep_score) or 0)})"
        lines.append(bit)

    limiter = s.get("limiting_factor")
    if limiter:
        pct = s.get("limiting_factor_percent")
        bit = f"- **Limiter:** {_titleize(limiter)}"
        if pct is not None:
            bit += f" ({pct}%)"
        lines.append(bit)
        others = [n for n in (s.get("limiting_factors") or []) if n != limiter]
        if others:
            lines.append(f"- **Also soft:** {', '.join(_titleize(n) for n in others)}")

    return lines


def _load_lines(summary: dict[str, Any]) -> list[str]:
    s = summary.get("load") or {}
    v = summary.get("volume") or {}
    lines: list[str] = ["## Load & Trends", ""]

    if s.get("acwr") is not None:
        bit = f"- **ACWR:** {s['acwr']}"
        if s.get("acwr_status"):
            bit += f" ({s['acwr_status']})"
        lines.append(bit)

    if v.get("distance_7d_km") is not None:
        bit = f"- **7-day volume:** {v['distance_7d_km']}km"
        delta = v.get("distance_7d_vs_28d_avg_pct")
        if delta is not None:
            bit += f" ({delta:+.0f}% vs 28-day avg)"
        lines.append(bit)

    if v.get("percent_of_tolerance") is not None:
        bit = f"- **Running tolerance:** {v['percent_of_tolerance']}%"
        if v.get("tolerance_status"):
            bit += f" ({v['tolerance_status']})"
        lines.append(bit)

    gaps = s.get("load_balance_gaps") or {}
    off = [
        f"{_titleize(name)} {int(info['gap']):+d}"
        for name, info in gaps.items()
        if isinstance(info, dict) and info.get("state") != "in_target"
    ]
    if off:
        lines.append(f"- **Load balance off target:** {', '.join(off)}")
    elif gaps:
        lines.append("- **Load balance:** all buckets in target")

    trends = summary.get("recovery_trends") or {}
    if trends.get("sleep_7d_avg_h") is not None:
        bit = f"- **Sleep (7d avg):** {_hours(trends['sleep_7d_avg_h'])}"
        below = trends.get("sleep_nights_below_need")
        if below:
            bit += f", {below}/7 nights below need"
        if trends.get("sleep_trend"):
            bit += f", trending {_ARROW.get(trends['sleep_trend'], trends['sleep_trend'])}"
        lines.append(bit)
    if trends.get("resting_hr_7d_avg") is not None:
        bit = f"- **RHR (7d avg):** {trends['resting_hr_7d_avg']}"
        if trends.get("resting_hr_trend"):
            bit += f", trending {_ARROW.get(trends['resting_hr_trend'], trends['resting_hr_trend'])}"
        lines.append(bit)
    if trends.get("hrv_trend"):
        lines.append(f"- **HRV:** trending {_ARROW.get(trends['hrv_trend'], trends['hrv_trend'])}")

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
            te_bits.append(f"aerobic {te['aerobic']}")
        if te.get("anaerobic") is not None:
            te_bits.append(f"anaerobic {te['anaerobic']}")
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


def render(metrics: dict[str, Any], activities: dict[str, Any] | None) -> str:
    summary = metrics.get("summary")
    if not isinstance(summary, dict):
        summary = build_summary(metrics)

    date = metrics.get("date", "")
    out: list[str] = [f"# Daily Check — {date}".rstrip(), ""]
    out.extend(_readiness_lines(metrics, summary))
    out.append("")
    out.extend(_today_lines(date, activities))
    out.append("")

    load_lines = _load_lines(summary)
    if load_lines:
        out.extend(load_lines)
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
        f.write(render(metrics, activities))
    print(out_path)


if __name__ == "__main__":
    main()

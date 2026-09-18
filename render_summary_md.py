"""Render latest_summary.md -- the phone-readable daily check.

Reads the already-generated latest_metrics.json / latest_activities.json and
writes a short markdown digest next to them. Purely a view over existing
files: it never calls the Garmin API and never changes the JSON.
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
    return name.replace("_", " ")


def _readiness_lines(payload: dict[str, Any], summary: dict[str, Any]) -> list[str]:
    readiness = payload.get("readiness") or {}
    s = summary.get("readiness") or {}
    lines: list[str] = []

    score = s.get("score")
    level = s.get("level")
    feedback = readiness.get("feedback")
    headline = f"**Readiness {score if score is not None else '-'}/100**"
    if level:
        headline += f" — {level}"
    if feedback:
        headline += f" ({feedback})"
    lines.append(headline)

    limiter = s.get("limiting_factor")
    if limiter:
        pct = s.get("limiting_factor_percent")
        detail = f"Limiter: {_titleize(limiter)}"
        if pct is not None:
            detail += f" ({pct}%)"
        others = [n for n in (s.get("limiting_factors") or []) if n != limiter]
        if others:
            detail += f"; also soft: {', '.join(_titleize(n) for n in others)}"
        lines.append(detail)

    rhr = readiness.get("resting_hr")
    hrv = readiness.get("hrv_last_night_avg_ms")
    hrv7 = readiness.get("hrv_7_day_avg_ms")
    band = (summary.get("recovery_trends") or {}).get("hrv_vs_balanced_band")
    bits = []
    if rhr is not None:
        bits.append(f"RHR {int(_num(rhr) or 0)}")
    if hrv is not None:
        hrv_bit = f"HRV {int(_num(hrv) or 0)}ms"
        if hrv7 is not None:
            hrv_bit += f" (7d {int(_num(hrv7) or 0)})"
        if band and band != "within":
            hrv_bit += f" [{band} band]"
        bits.append(hrv_bit)
    sleep_h = readiness.get("sleep_hours")
    sleep_score = readiness.get("sleep_score")
    if sleep_h is not None:
        sleep_bit = f"Sleep {_hours(sleep_h)}"
        if sleep_score is not None:
            sleep_bit += f" (score {int(_num(sleep_score) or 0)})"
        bits.append(sleep_bit)
    if bits:
        lines.append(" · ".join(bits))
    return lines


def _load_lines(summary: dict[str, Any]) -> list[str]:
    s = summary.get("load") or {}
    v = summary.get("volume") or {}
    lines: list[str] = []

    bits = []
    if s.get("acwr") is not None:
        acwr_bit = f"ACWR {s['acwr']}"
        if s.get("acwr_status"):
            acwr_bit += f" ({s['acwr_status']})"
        bits.append(acwr_bit)
    if v.get("distance_7d_km") is not None:
        vol_bit = f"7d {v['distance_7d_km']}km"
        delta = v.get("distance_7d_vs_28d_avg_pct")
        if delta is not None:
            vol_bit += f" ({delta:+.0f}% vs 28d avg)"
        bits.append(vol_bit)
    if v.get("percent_of_tolerance") is not None:
        tol_bit = f"Tolerance {v['percent_of_tolerance']}%"
        if v.get("tolerance_status"):
            tol_bit += f" ({v['tolerance_status']})"
        bits.append(tol_bit)
    if bits:
        lines.append(" · ".join(bits))

    gaps = s.get("load_balance_gaps") or {}
    off = [
        f"{_titleize(name)} {int(info['gap']):+d}"
        for name, info in gaps.items()
        if isinstance(info, dict) and info.get("state") != "in_target"
    ]
    if off:
        lines.append(f"Load balance off target: {', '.join(off)}")
    elif gaps:
        lines.append("Load balance: all buckets in target")
    return lines


def _trend_lines(summary: dict[str, Any]) -> list[str]:
    s = summary.get("recovery_trends") or {}
    bits = []
    if s.get("sleep_7d_avg_h") is not None:
        sleep_bit = f"Sleep 7d avg {_hours(s['sleep_7d_avg_h'])}"
        below = s.get("sleep_nights_below_need")
        if below:
            sleep_bit += f" ({below}/7 below need)"
        if s.get("sleep_trend"):
            sleep_bit += f", {_ARROW.get(s['sleep_trend'], s['sleep_trend'])}"
        bits.append(sleep_bit)
    if s.get("resting_hr_7d_avg") is not None:
        rhr_bit = f"RHR 7d avg {s['resting_hr_7d_avg']}"
        if s.get("resting_hr_trend"):
            rhr_bit += f", {_ARROW.get(s['resting_hr_trend'], s['resting_hr_trend'])}"
        bits.append(rhr_bit)
    if s.get("hrv_trend"):
        bits.append(f"HRV {_ARROW.get(s['hrv_trend'], s['hrv_trend'])}")
    return [" · ".join(bits)] if bits else []


def _activity_lines(activities_payload: dict[str, Any] | None, date: Any) -> list[str]:
    if not isinstance(activities_payload, dict):
        return ["_No activity file found._"]
    activities = activities_payload.get("activities")
    if not isinstance(activities, list) or not activities:
        return ["_No activity logged._"]

    lines: list[str] = []
    for act in activities:
        if not isinstance(act, dict):
            continue
        name = act.get("name") or act.get("type") or "Activity"
        parts = [f"**{name}**"]
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
            parts.append(" · ".join(detail))
        lines.append(" — ".join(parts))

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
                lines.append(f"  TE: {' · '.join(te_bits)}")

        drift = act.get("interval_drift")
        if isinstance(drift, dict) and drift.get("work_reps"):
            drift_bits = [f"{drift['work_reps']} work reps"]
            if drift.get("pace_ef_drift_pct") is not None:
                drift_bits.append(f"pace drift {drift['pace_ef_drift_pct']:+}%")
            if drift.get("hr_delta_bpm") is not None:
                drift_bits.append(f"HR +{int(_num(drift['hr_delta_bpm']) or 0)}bpm")
            lines.append(f"  Intervals: {' · '.join(drift_bits)}")
    return lines or ["_No activity logged._"]


def render(metrics: dict[str, Any], activities: dict[str, Any] | None) -> str:
    summary = metrics.get("summary")
    if not isinstance(summary, dict):
        summary = build_summary(metrics)

    date = metrics.get("date", "")
    out: list[str] = [f"# Daily check — {date}".rstrip(), ""]

    out.extend(_readiness_lines(metrics, summary))
    out.append("")

    out.append("## Today")
    out.extend(_activity_lines(activities, date))
    out.append("")

    load_lines = _load_lines(summary)
    trend_lines = _trend_lines(summary)
    if load_lines or trend_lines:
        out.append("## Load & trends")
        out.extend(load_lines)
        out.extend(trend_lines)
        out.append("")

    return "\n".join(out).rstrip() + "\n"


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

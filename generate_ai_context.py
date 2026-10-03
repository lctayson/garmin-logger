#!/usr/bin/env python3
"""Generate a single compact, token-optimized file combining an endurance coach 
prompt, daily metrics JSON, and today's raw activity JSON for AI chat context.

Usage:
    python generate_ai_context.py --data-dir data
"""

import argparse
import json
import os

# Specialized system/context prompt for your elite AI endurance coach
COACH_PROMPT = """> Act as my elite, data-driven half-marathon coach for BHM 2027. Analyze the Garmin telemetry, recovery metrics, and raw activity data below. Evaluate workout execution, pacing, HR response, aerobic/threshold/VO₂ development, running economy, fatigue, and training-load progression, accounting for heat/humidity and recent training. Give concise, high-impact coaching insights and adjustments only when justified by the data. Prioritize the overall training block over individual workouts and don't chase Garmin metrics or labels."""

def _load_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def build_context(metrics, activities):
    parts = [COACH_PROMPT, "\n---"]
    
    # Minified Daily Metrics JSON
    parts.append("## Metrics")
    if metrics:
        # separators=(',', ':') removes all unnecessary spaces/newlines to save tokens
        metrics_minified = json.dumps(metrics, separators=(',', ':'), ensure_ascii=False)
        parts.append(f"```json\n{metrics_minified}\n```")
    else:
        parts.append("(No metrics available.)")

    # Minified Activities JSON
    parts.append("\n## Activities")
    has_activities = (
        isinstance(activities, dict)
        and isinstance(activities.get("activities"), list)
        and len(activities["activities"]) > 0
    )

    if has_activities:
        activities_minified = json.dumps(activities, separators=(',', ':'), ensure_ascii=False)
        parts.append(f"```json\n{activities_minified}\n```")
    else:
        parts.append("(No activity logged.)")

    return "\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--metrics", default=None, help="Defaults to <data-dir>/latest_metrics.json")
    parser.add_argument("--activities", default=None, help="Defaults to <data-dir>/latest_activities.json")
    parser.add_argument("--out", default=None, help="Defaults to <data-dir>/ai_context.md")
    args = parser.parse_args()

    metrics_path = args.metrics or os.path.join(args.data_dir, "latest_metrics.json")
    activities_path = args.activities or os.path.join(args.data_dir, "latest_activities.json")
    out_path = args.out or os.path.join(args.data_dir, "ai_context.md")

    metrics = _load_json(metrics_path)
    if metrics is None:
        raise SystemExit(f"could not read metrics file: {metrics_path}")
    activities = _load_json(activities_path)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(build_context(metrics, activities))
    print(out_path)


if __name__ == "__main__":
    main()
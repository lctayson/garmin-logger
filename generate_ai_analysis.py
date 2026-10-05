#!/usr/bin/env python3
"""Generate a short AI coaching analysis for each of the day's activities,
using the enriched activity/metrics JSON plus training_context.md for
persistent grounding (goal, phase, methodology, known risk factors).

Runs between split_garmin_json.py and render_summary_md.py in the daily
pipeline: needs the day's enriched activity JSON to already exist, and
render_summary_md.py picks up the "ai_analysis" field this writes.

Supports two providers -- flip between them with --provider, no other
code changes needed:

    python generate_ai_analysis.py --date 2026-09-28 --provider gemini
    python generate_ai_analysis.py --date 2026-09-28 --provider anthropic

Requires GEMINI_API_KEY or ANTHROPIC_API_KEY in the environment,
matching whichever --provider is selected.
"""

import argparse
import json
import os
import sys

from render_summary_md import _find_dated_activity_file, _load_json

DEFAULT_MODELS = {
    "gemini": "gemini-3.8-flash",
    "anthropic": "claude-sonnet-5",
}
MAX_OUTPUT_TOKENS = 600

SYSTEM_PREFIX = """You are Onin's endurance running coach. You write short, \
specific analysis of a single workout he just completed, grounded in the \
actual data below -- never generic praise, never a template with numbers \
swapped in. If something is unremarkable, say so plainly rather than \
manufacturing a concern.

Durable coaching context (goal, current phase, methodology, known risk \
factors to watch for):

"""

READINESS_SYSTEM_PREFIX = """You are Onin's endurance running coach. No \
activity has been logged yet today. Using his current readiness/recovery \
data and the typical schedule for today's day-of-week (both in the \
durable context below), give a short, specific recommendation: proceed \
with today's normal session as planned, modify it (how, specifically), \
or rest. Never generic "listen to your body" filler -- say what you'd \
actually do given these specific numbers. If readiness looks fine, say so \
plainly rather than manufacturing caution.

Durable coaching context (goal, current phase, methodology, known risk \
factors, and today's typical scheduled session):

"""


def _build_prompt(activity, metrics):
    """Keep the payload small and relevant -- not a full raw JSON dump."""
    fields = (
        "name", "type", "distance", "time", "avg_pace", "avg_hr", "max_hr",
        "training_effect", "interval_drift", "performance_condition",
        "stamina", "body_battery_impact", "load",
    )
    trimmed_activity = {k: activity[k] for k in fields if k in activity}

    readiness = (metrics or {}).get("readiness") or {}
    trimmed_readiness = {
        k: readiness[k]
        for k in ("score", "level", "feedback", "resting_hr", "sleep_score", "recovery_hours")
        if k in readiness
    }

    return json.dumps({"activity": trimmed_activity, "readiness_that_day": trimmed_readiness}, indent=2)


def _build_readiness_prompt(metrics, date_str):
    import datetime
    weekday = datetime.date.fromisoformat(date_str).strftime("%A")
    readiness = (metrics or {}).get("readiness") or {}
    load = (metrics or {}).get("load") or {}
    trimmed_readiness = {
        k: readiness[k]
        for k in (
            "score", "level", "feedback", "resting_hr", "hrv_last_night_avg_ms",
            "hrv_7_day_avg_ms", "hrv_status", "sleep_hours", "sleep_score",
            "recovery_hours", "factor_details",
        )
        if k in readiness
    }
    trimmed_load = {
        k: load[k]
        for k in ("acute_load", "chronic_load", "acwr", "acwr_status", "load_focus", "vo2_max")
        if k in load
    }
    return json.dumps(
        {"day_of_week": weekday, "readiness": trimmed_readiness, "load": trimmed_load},
        indent=2,
    )


def generate_readiness_analysis(provider, model, context_text, metrics, date_str):
    prompt = _build_readiness_prompt(metrics, date_str)
    system = READINESS_SYSTEM_PREFIX + context_text
    user_content = f"Today's readiness data (no activity logged yet):\n\n{prompt}"
    return PROVIDER_CALLERS[provider](model, system, user_content)


def _call_anthropic(model, system, user_content):
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    # SDK already retries transient errors (529 overloaded, timeouts, etc.)
    # automatically -- default is 2, bumped up since this runs unattended
    # in CI with nobody waiting on a live response.
    client = anthropic.Anthropic(api_key=api_key, max_retries=5)
    response = client.messages.create(
        model=model,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )
    parts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
    return "".join(parts).strip()


def _call_gemini(model, system, user_content):
    from google import genai
    from google.genai import types
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    # The SDK does NOT retry by default (retry_options is None unless set
    # explicitly) -- a transient 503 (model overloaded, routine and
    # temporary) fails outright on the first attempt otherwise.
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(
                attempts=5,
                initial_delay=1.0,
                max_delay=20.0,
                exp_base=2.0,
                http_status_codes=[408, 429, 500, 502, 503, 504],
            ),
        ),
    )

    # Handle thinking configuration based on model version family
    if "gemini-3" in model:
        thinking_cfg = types.ThinkingConfig(thinking_level="low")
    else:
        thinking_cfg = types.ThinkingConfig(thinking_budget=0)

    response = client.models.generate_content(
        model=model,
        contents=user_content,
        config=types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            thinking_config=thinking_cfg,
        ),
    )
    return (response.text or "").strip()


PROVIDER_CALLERS = {
    "anthropic": _call_anthropic,
    "gemini": _call_gemini,
}


def generate_for_activity(provider, model, context_text, activity, metrics):
    prompt = _build_prompt(activity, metrics)
    system = SYSTEM_PREFIX + context_text
    user_content = f"Today's workout data:\n\n{prompt}"
    return PROVIDER_CALLERS[provider](model, system, user_content)


def _run_readiness_mode(args, model, context_text, metrics, metrics_path):
    if not isinstance(metrics, dict) or not metrics.get("readiness"):
        print("[generate_ai_analysis] No activity and no readiness data for this date -- nothing to do.", file=sys.stderr)
        return

    readiness = metrics["readiness"]
    if readiness.get("ai_analysis") and not args.force:
        print("[generate_ai_analysis] Readiness analysis already set for this date -- skipping (use --force to regenerate).", file=sys.stderr)
        return

    try:
        analysis = generate_readiness_analysis(args.provider, model, context_text, metrics, args.date)
    except Exception as e:
        print(f"[generate_ai_analysis] {args.provider} call failed for readiness analysis: {e}", file=sys.stderr)
        return
    if not analysis:
        return

    readiness["ai_analysis"] = analysis
    readiness["ai_analysis_provider"] = f"{args.provider}:{model}"
    print(f"[generate_ai_analysis] Generated readiness-based analysis via {args.provider} (no activity logged yet).", file=sys.stderr)

    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # Keep latest_metrics.json in sync if it's the same day.
    latest_metrics_path = os.path.join(args.data_dir, "latest_metrics.json")
    if os.path.exists(latest_metrics_path):
        latest_metrics = _load_json(latest_metrics_path)
        if isinstance(latest_metrics, dict) and latest_metrics.get("date") == args.date:
            latest_metrics.setdefault("readiness", {})["ai_analysis"] = analysis
            latest_metrics["readiness"]["ai_analysis_provider"] = f"{args.provider}:{model}"
            with open(latest_metrics_path, "w", encoding="utf-8") as f:
                json.dump(latest_metrics, f, indent=2, ensure_ascii=False)
                f.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--context", default="training_context.md")
    parser.add_argument("--provider", choices=("gemini", "anthropic"), default="gemini")
    parser.add_argument("--model", default=None, help="Defaults per-provider if not given")
    parser.add_argument("--force", action="store_true", help="Regenerate even if ai_analysis already set")
    args = parser.parse_args()
    model = args.model or DEFAULT_MODELS[args.provider]

    key_var = "GEMINI_API_KEY" if args.provider == "gemini" else "ANTHROPIC_API_KEY"
    if not os.environ.get(key_var):
        print(f"[generate_ai_analysis] {key_var} not set -- skipping.", file=sys.stderr)
        return

    if not os.path.exists(args.context):
        print(f"[generate_ai_analysis] {args.context} not found -- skipping.", file=sys.stderr)
        return
    with open(args.context, "r", encoding="utf-8") as f:
        context_text = f.read()

    metrics_path = os.path.join(args.data_dir, args.date[:4], args.date[5:7], f"{args.date}_metrics.json")
    metrics = _load_json(metrics_path) if os.path.exists(metrics_path) else None

    activity_path = _find_dated_activity_file(args.data_dir, args.date)
    activities_payload = _load_json(activity_path) if activity_path else None
    activities = (activities_payload or {}).get("activities") if isinstance(activities_payload, dict) else None

    _run_readiness_mode(args, model, context_text, metrics, metrics_path)
    if not isinstance(activities, list) or not activities:
        # No workout logged (yet, or a rest day) -- fall back to a
        # readiness-only recommendation instead of doing nothing.
        return

    changed = False
    for activity in activities:
        if not isinstance(activity, dict):
            continue
        if activity.get("ai_analysis") and not args.force:
            continue
        try:
            analysis = generate_for_activity(args.provider, model, context_text, activity, metrics)
        except Exception as e:
            print(f"[generate_ai_analysis] {args.provider} call failed for '{activity.get('name')}': {e}", file=sys.stderr)
            continue
        if analysis:
            activity["ai_analysis"] = analysis
            activity["ai_analysis_provider"] = f"{args.provider}:{model}"
            changed = True
            print(f"[generate_ai_analysis] Generated analysis for '{activity.get('name')}' via {args.provider}.", file=sys.stderr)

    if not changed:
        return

    with open(activity_path, "w", encoding="utf-8") as f:
        json.dump(activities_payload, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # Keep latest_activities.json in sync if it's the same day.
    latest_path = os.path.join(args.data_dir, "latest_activities.json")
    if os.path.exists(latest_path):
        latest_payload = _load_json(latest_path)
        if isinstance(latest_payload, dict) and latest_payload.get("date") == args.date:
            with open(latest_path, "w", encoding="utf-8") as f:
                json.dump(activities_payload, f, indent=2, ensure_ascii=False)
                f.write("\n")


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""Generate a short AI coaching analysis for each of the day's activities,
using the enriched activity/metrics JSON plus training_context.md for
persistent grounding (goal, phase, methodology, known risk factors).

Runs between split_garmin_json.py and render_summary_md.py in the daily
pipeline: needs the day's enriched activity JSON to already exist, and
render_summary_md.py picks up the "ai_analysis" field this writes.

Supports three providers -- flip between them with --provider:

    python generate_ai_analysis.py --date 2026-09-28 --provider gemini
    python generate_ai_analysis.py --date 2026-09-28 --provider anthropic
    python generate_ai_analysis.py --date 2026-09-28 --provider github

Requires GEMINI_API_KEY, ANTHROPIC_API_KEY, or GITHUB_TOKEN in the environment.
"""

import argparse
import json
import os
import sys
import datetime

from render_summary_md import _find_dated_activity_file, _load_json

DEFAULT_MODELS = {
    "gemini": "gemini-3.8-flash",
    "anthropic": "claude-sonnet-5",
    "github": "openai/gpt-4o",  # Alternatives: "gpt-4o-mini", "meta-llama-3.3-70b-instruct"
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


def _call_github(model: str, system: str, user_content: str) -> str:
    """Call GitHub Models inference endpoint via OpenAI client."""
    from openai import OpenAI

    token = (
        os.environ.get("GITHUB_TOKEN")
        or os.environ.get("GH_MODELS_TOKEN")
        or os.environ.get("GH_TOKEN")
    )
    if not token:
        raise RuntimeError("No GitHub token set in environment")

    client = OpenAI(
        base_url="https://models.github.ai/inference",
        api_key=token,
        timeout=60.0,
    )

    model_name = model if "/" in model else f"openai/{model}"

    response = client.chat.completions.create(
        model=model_name,
        max_tokens=MAX_OUTPUT_TOKENS,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
    )

    # Standard OpenAI SDK response handling
    if hasattr(response, "choices") and response.choices:
        content = response.choices[0].message.content
        if content and content.strip():
            return content.strip()
            
    # Debug print if model returned no text content
    print(f"[generate_ai_analysis] Raw GitHub response object: {response}", file=sys.stderr)
    return ""


PROVIDER_CALLERS = {
    "anthropic": _call_anthropic,
    "gemini": _call_gemini,
    "github": _call_github,
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
    default_date = datetime.datetime.now().strftime("%Y-%m-%d")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", default=default_date, help="YYYY-MM-DD")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--context", default="training_context.md")
    parser.add_argument("--provider", choices=("gemini", "anthropic", "github"), default="github")
    parser.add_argument("--model", default=None, help="Defaults per-provider if not given")
    parser.add_argument("--force", action="store_true", help="Regenerate even if ai_analysis already set")
    args = parser.parse_args()
    
    model = args.model or DEFAULT_MODELS[args.provider]

    key_map = {
        "gemini": "GEMINI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "github": "GITHUB_TOKEN",
    }
    key_var = key_map[args.provider]
    
    # Normalize GH_TOKEN -> GITHUB_TOKEN if using github provider
    if args.provider == "github" and not os.environ.get("GITHUB_TOKEN") and os.environ.get("GH_TOKEN"):
        os.environ["GITHUB_TOKEN"] = os.environ["GH_TOKEN"]

    if not os.environ.get(key_var):
        print(f"[generate_ai_analysis] {key_var} not set -- skipping.", file=sys.stderr)
        return

    if not os.path.exists(args.context):
        print(f"[generate_ai_analysis] {args.context} not found -- skipping.", file=sys.stderr)
        return
        
    with open(args.context, "r", encoding="utf-8") as f:
        context_text = f.read()

    # Safe path building
    date_parts = args.date.split("-")
    if len(date_parts) >= 2:
        metrics_path = os.path.join(args.data_dir, date_parts[0], date_parts[1], f"{args.date}_metrics.json")
    else:
        metrics_path = os.path.join(args.data_dir, f"{args.date}_metrics.json")

    metrics = _load_json(metrics_path) if os.path.exists(metrics_path) else None

    activity_path = _find_dated_activity_file(args.data_dir, args.date)
    activities_payload = _load_json(activity_path) if activity_path else None

    # Handle both top-level list and wrapped dict structures
    if isinstance(activities_payload, list):
        activities = activities_payload
    elif isinstance(activities_payload, dict):
        activities = activities_payload.get("activities")
    else:
        activities = None

    if not isinstance(activities, list) or not activities:
        _run_readiness_mode(args, model, context_text, metrics, metrics_path)
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

    latest_path = os.path.join(args.data_dir, "latest_activities.json")
    if os.path.exists(latest_path):
        latest_payload = _load_json(latest_path)
        if isinstance(latest_payload, dict) and latest_payload.get("date") == args.date:
            with open(latest_path, "w", encoding="utf-8") as f:
                json.dump(activities_payload, f, indent=2, ensure_ascii=False)
                f.write("\n")


if __name__ == "__main__":
    main()
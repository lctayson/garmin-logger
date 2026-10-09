#!/usr/bin/env python3
"""Generate a short AI coaching analysis for each of the day's activities,
using the enriched activity/metrics JSON plus training_context.md for
persistent grounding (goal, phase, methodology, known risk factors).

Runs between split_garmin_json.py and render_summary_md.py in the daily
pipeline: needs the day's enriched activity JSON to already exist, and
render_summary_md.py picks up the "ai_analysis" field this writes.

Supports five providers -- flip between them with --provider:

    python generate_ai_analysis.py --date 2026-10-06 --provider gemini
    python generate_ai_analysis.py --date 2026-10-06 --provider anthropic
    python generate_ai_analysis.py --date 2026-10-06 --provider groq
    python generate_ai_analysis.py --date 2026-10-06 --provider deepseek
    python generate_ai_analysis.py --date 2026-10-06 --provider github

Requires GEMINI_API_KEY, ANTHROPIC_API_KEY, GROQ_API_KEY, DEEPSEEK_API_KEY, or GITHUB_TOKEN.
"""
import os
import argparse
import datetime
import json
import os
import sys

from render_summary_md import _find_dated_activity_file, _load_json

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv is not installed in CI/CD; relying on shell/GitHub Actions environment

DEFAULT_MODELS = {
    "gemini": "gemini-3.8-flash",
    "anthropic": "claude-sonnet-5",
    "groq": "openai/gpt-oss-120b",  # llama-3.3-70b-versatile was decommissioned 2026-08-16
    "deepseek": "deepseek-chat",  # Options: "deepseek-chat", "deepseek-reasoner"
    "github": "openai/gpt-4o",  # Dead: GitHub Models was fully retired 2026-07-30. Do not use.
}

PROVIDER_CONFIGS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_env": "GROQ_API_KEY",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "github": {
        "base_url": "https://models.github.ai/inference",
        "api_key_env": "GITHUB_TOKEN",
    },
}

MAX_OUTPUT_TOKENS = 600

SYSTEM_PREFIX = """You are Onin's endurance running coach. Write a short, specific analysis of a single workout, grounded in the actual data. Avoid generic praise, canned templates, and manufactured concerns. Write 2–4 complete sentences; never end mid-sentence.

Workout-analysis rules:
- For interval sessions, assess execution from the actual work reps in the supplied main_set data, not from whole-activity average pace. Overall pace includes warm-up, recoveries, and cooldown.
- Compare rep pace with a prescribed target only when that target is explicitly supported by the workout prescription or durable coaching context. If rep data is missing, say pace execution cannot be verified; do not infer a miss from overall average pace.
- interval_drift.pace_ef_drift_pct is a change in pace/efficiency across reps, not the percentage by which the rep pace missed its target. Interpret it alongside rep paces and HR/power changes; do not conflate the measures.
- Do not claim the workout's cardiovascular load came mainly from HR spikes, or attribute drift to heat/fatigue, unless the supplied evidence supports it.
- Treat readiness_that_day as the morning readiness score, not a post-run readiness snapshot.

Durable coaching context (goal, current phase, methodology, and known risk factors to watch for):

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


def _parse_clock_seconds(value):
    """Parse Garmin split durations/pace strings such as '3:00' or '5:08'."""
    if not isinstance(value, str):
        return None
    parts = value.split(":")
    try:
        numbers = [int(part) for part in parts]
    except ValueError:
        return None
    if len(numbers) == 2:
        return numbers[0] * 60 + numbers[1]
    if len(numbers) == 3:
        return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    return None


def _format_clock_pace(seconds):
    minutes = int(seconds // 60)
    remainder = int(round(seconds - minutes * 60))
    if remainder >= 60:
        minutes += 1
        remainder = 0
    return f"{minutes}:{remainder:02d}"


def _main_set_summary(activity):
    """Extract the largest-duration group of work splits without copying all laps into the prompt."""
    splits = activity.get("splits")
    if not isinstance(splits, dict):
        return None
    columns, rows = splits.get("columns"), splits.get("data")
    if not isinstance(columns, list) or not isinstance(rows, list):
        return None
    col = {name: i for i, name in enumerate(columns)}
    if not all(name in col for name in ("step_type", "time", "avg_pace")):
        return None

    active = [
        row for row in rows
        if isinstance(row, list)
        and col["step_type"] < len(row)
        and str(row[col["step_type"]]).upper() in ("ACTIVE", "INTERVAL")
    ]
    if len(active) < 2:
        return None

    def cell(row, name):
        idx = col.get(name)
        return row[idx] if idx is not None and idx < len(row) else None

    def duration(row):
        return _parse_clock_seconds(cell(row, "time")) or 0

    step_col = col.get("workout_step_index")
    groups = {}
    if step_col is not None:
        for row in active:
            groups.setdefault(cell(row, "workout_step_index"), []).append(row)
    if len(groups) <= 1:
        # Some Garmin exports omit step indexes; separate long work reps from
        # short strides using duration, matching the summary renderer's rule.
        groups = {}
        for row in active:
            key = "long" if duration(row) >= 60 else "short"
            groups.setdefault(key, []).append(row)
    if not groups:
        return None

    work_rows = max(groups.values(), key=lambda group: sum(duration(row) for row in group))
    reps = []
    for row in work_rows:
        pace = cell(row, "avg_pace")
        pace_seconds = _parse_clock_seconds(pace)
        if pace_seconds is None or duration(row) <= 0:
            continue
        rep = {"duration": cell(row, "time"), "pace": pace}
        hr = cell(row, "avg_hr")
        if hr is not None:
            rep["avg_hr"] = hr
        reps.append((pace_seconds, rep))
    if len(reps) < 2:
        return None

    pace_seconds = [item[0] for item in reps]
    durations = [item[1]["duration"] for item in reps]
    result = {
        "work_reps": len(reps),
        "rep_paces": [item[1]["pace"] for item in reps],
        "average_rep_pace": _format_clock_pace(sum(pace_seconds) / len(pace_seconds)),
        "pace_range": [
            _format_clock_pace(min(pace_seconds)),
            _format_clock_pace(max(pace_seconds)),
        ],
    }
    if len(set(durations)) == 1:
        result["rep_duration"] = durations[0]
    if all("avg_hr" in item[1] for item in reps):
        result["rep_avg_hr"] = [item[1]["avg_hr"] for item in reps]
    return result


def _build_prompt(activity, metrics):
    fields = (
        "name", "type", "distance", "time", "avg_pace", "avg_hr", "max_hr",
        "training_effect", "interval_drift", "performance_condition",
        "stamina", "body_battery_impact", "load",
    )
    trimmed_activity = {k: activity[k] for k in fields if k in activity}
    main_set = _main_set_summary(activity)
    if main_set:
        trimmed_activity["main_set"] = main_set

    readiness = (metrics or {}).get("readiness") or {}
    trimmed_readiness = {
        k: readiness[k]
        for k in ("score", "level", "feedback", "resting_hr", "sleep_score", "recovery_hours")
        if k in readiness
    }

    return json.dumps({"activity": trimmed_activity, "readiness_that_day": trimmed_readiness}, indent=2)


def _build_readiness_prompt(metrics, date_str):
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


def _call_openai_compatible(
    model: str,
    system: str,
    user_content: str,
    base_url: str,
    api_key_env: str,
) -> str:
    """Generic caller for OpenAI-compatible providers (Groq, DeepSeek, GitHub Models, OpenRouter)."""
    from openai import OpenAI

    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise RuntimeError(f"{api_key_env} is not set.")

    client = OpenAI(base_url=base_url, api_key=api_key, timeout=60.0)

    # Normalize model string for GitHub Models if namespace omitted
    if "github" in base_url and "/" not in model:
        model = f"openai/{model}"

    # Expand token limit for reasoning models to accommodate internal thinking steps
    max_tokens = 4000 if "reasoner" in model or "r1" in model.lower() else MAX_OUTPUT_TOKENS

    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
    )

    if hasattr(response, "choices") and response.choices:
        content = response.choices[0].message.content
        if content and content.strip():
            return content.strip()

    # An empty response must raise, not return "" -- a silent empty return
    # looks like success (exit code 0) to the shell, so the `provider_a ||
    # provider_b` fallback in the workflow YAML never triggers and nothing
    # gets generated with no visible error at all.
    raise RuntimeError(f"Empty response from {base_url} (model={model}): {response}")


def _require_nonempty(text: str, source: str) -> str:
    """A silently-empty result looks like success (exit code 0) to the
    shell, so the `provider_a || provider_b` fallback in the workflow YAML
    never triggers and nothing gets generated with no visible error. Every
    provider caller must raise on empty output, not return "" quietly."""
    text = (text or "").strip()
    if not text:
        raise RuntimeError(f"Empty response from {source}")
    return text


def _call_anthropic(model: str, system: str, user_content: str) -> str:
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
    return _require_nonempty("".join(parts), f"anthropic:{model}")


def _call_gemini(model: str, system: str, user_content: str) -> str:
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

    thinking_cfg = (
        types.ThinkingConfig(thinking_level="low")
        if "gemini-3" in model
        else types.ThinkingConfig(thinking_budget=0)
    )

    response = client.models.generate_content(
        model=model,
        contents=user_content,
        config=types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            thinking_config=thinking_cfg,
        ),
    )
    return _require_nonempty(response.text, f"gemini:{model}")


def execute_provider_call(provider: str, model: str, system: str, user_content: str) -> str:
    """Routes provider call to native SDK or generic OpenAI-compatible function."""
    if provider == "gemini":
        return _call_gemini(model, system, user_content)
    elif provider == "anthropic":
        return _call_anthropic(model, system, user_content)
    elif provider in PROVIDER_CONFIGS:
        cfg = PROVIDER_CONFIGS[provider]
        return _call_openai_compatible(
            model=model,
            system=system,
            user_content=user_content,
            base_url=cfg["base_url"],
            api_key_env=cfg["api_key_env"],
        )
    else:
        raise ValueError(f"Unsupported provider: {provider}")


def generate_for_activity(provider, model, context_text, activity, metrics):
    prompt = _build_prompt(activity, metrics)
    system = SYSTEM_PREFIX + context_text
    user_content = f"Today's workout data:\n\n{prompt}"
    return execute_provider_call(provider, model, system, user_content)


def generate_readiness_analysis(provider, model, context_text, metrics, date_str):
    prompt = _build_readiness_prompt(metrics, date_str)
    system = READINESS_SYSTEM_PREFIX + context_text
    user_content = f"Today's readiness data (no activity logged yet):\n\n{prompt}"
    return execute_provider_call(provider, model, system, user_content)


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
        # A genuine failure, not "nothing to do" -- must exit non-zero so
        # the `provider_a || provider_b` fallback in the workflow YAML
        # actually triggers, the same reason every provider caller now
        # raises instead of returning "" on empty output.
        print(f"[generate_ai_analysis] {args.provider} call failed for readiness analysis: {e}", file=sys.stderr)
        sys.exit(1)
    if not analysis:
        print(f"[generate_ai_analysis] {args.provider} returned an empty readiness analysis.", file=sys.stderr)
        sys.exit(1)

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
    parser.add_argument("--date", default=default_date, help="YYYY-MM-DD (defaults to today)")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--context", default="training_context.md")
    parser.add_argument(
        "--provider",
        choices=("gemini", "anthropic", "groq", "deepseek", "github"),
        default="gemini",
    )
    parser.add_argument("--model", default=None, help="Defaults per-provider if not given")
    parser.add_argument("--force", action="store_true", help="Regenerate even if ai_analysis already set")
    args = parser.parse_args()

    model = args.model or DEFAULT_MODELS[args.provider]

    key_map = {
        "gemini": "GEMINI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "groq": "GROQ_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "github": "GITHUB_TOKEN",
    }
    key_var = key_map[args.provider]

    # Support token aliases for GitHub
    if args.provider == "github" and not os.environ.get("GITHUB_TOKEN"):
        token_alias = os.environ.get("GH_MODELS_TOKEN") or os.environ.get("GH_TOKEN")
        if token_alias:
            os.environ["GITHUB_TOKEN"] = token_alias

    if not os.environ.get(key_var):
        print(f"[generate_ai_analysis] {key_var} not set -- skipping.", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(args.context):
        print(f"[generate_ai_analysis] {args.context} not found -- skipping.", file=sys.stderr)
        return

    with open(args.context, "r", encoding="utf-8") as f:
        context_text = f.read()

    # Build date-specific metrics path safely
    date_parts = args.date.split("-")
    if len(date_parts) >= 2:
        metrics_path = os.path.join(args.data_dir, date_parts[0], date_parts[1], f"{args.date}_metrics.json")
    else:
        metrics_path = os.path.join(args.data_dir, f"{args.date}_metrics.json")

    metrics = _load_json(metrics_path) if os.path.exists(metrics_path) else None

    activity_path = _find_dated_activity_file(args.data_dir, args.date)
    activities_payload = _load_json(activity_path) if activity_path else None

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
    failed = False
    for activity in activities:
        if not isinstance(activity, dict):
            continue
        if activity.get("ai_analysis") and not args.force:
            continue
        try:
            analysis = generate_for_activity(args.provider, model, context_text, activity, metrics)
        except Exception as e:
            # Keep going so other activities can still succeed, and remember
            # to exit non-zero at the end so the workflow's fallback
            # provider runs (it skips activities that already have analysis).
            print(f"[generate_ai_analysis] {args.provider} call failed for '{activity.get('name')}': {e}", file=sys.stderr)
            failed = True
            continue

        if analysis:
            activity["ai_analysis"] = analysis
            activity["ai_analysis_provider"] = f"{args.provider}:{model}"
            changed = True
            print(f"[generate_ai_analysis] Generated analysis for '{activity.get('name')}' via {args.provider}.", file=sys.stderr)

    if not changed:
        if failed:
            sys.exit(1)
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

    # Partial progress is saved above; now signal that something still
    # failed so the fallback provider picks up the remainder.
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
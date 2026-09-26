#!/usr/bin/env python3
"""Manage data/performance_log.json -- your manually-verified races, controlled
tests, and personal bests. This is a coaching record, not Garmin-derived data;
Garmin's own race predictions live in latest_metrics.json instead (see
compact_metrics.py). Keeping the two separate avoids duplicate sources of
truth for the same numbers.

Usage:
    python performance_log.py add-race --date 2026-09-20 --event "BMH 10K" \\
        --distance-km 10.0 --time 57:56 [--pace 5:48/km] [--avg-hr 168] \\
        [--max-hr 179] [--notes "..."]

    python performance_log.py add-test --date 2026-10-11 --kind "5K test" \\
        --distance-km 5.0 --time 24:10 [--notes "..."]

    python performance_log.py set-pb --distance half_marathon --time 1:59:23 \\
        --date 2026-02 --event "BHM 2026 Half Marathon" --tier recent

    python performance_log.py show
"""

import argparse
import json
import os

DEFAULT_PATH = os.path.join("data", "performance_log.json")


def _load(path):
    if not os.path.exists(path):
        return {"races": [], "tests": [], "personal_bests": {}}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _entry_from_args(args, kind_key=None, kind_value=None):
    entry = {"date": args.date, "event": args.event}
    if kind_key:
        entry[kind_key] = kind_value
    if args.distance_km is not None:
        entry["distance_km"] = args.distance_km
    if args.time:
        entry["time"] = args.time
    if getattr(args, "pace", None):
        entry["pace"] = args.pace
    if getattr(args, "avg_hr", None) is not None:
        entry["avg_hr"] = args.avg_hr
    if getattr(args, "max_hr", None) is not None:
        entry["max_hr"] = args.max_hr
    if args.notes:
        entry["notes"] = args.notes
    return entry


def cmd_add_race(args):
    data = _load(args.file)
    entry = _entry_from_args(args, kind_key="type", kind_value="race")
    data.setdefault("races", []).append(entry)
    data["races"].sort(key=lambda r: r.get("date", ""))
    _save(args.file, data)
    print(f"Added race: {entry['date']} {entry['event']} -- {entry.get('time', '?')}")


def cmd_add_test(args):
    data = _load(args.file)
    entry = _entry_from_args(args, kind_key="kind", kind_value=args.kind)
    data.setdefault("tests", []).append(entry)
    data["tests"].sort(key=lambda t: t.get("date", ""))
    _save(args.file, data)
    print(f"Added test: {entry['date']} {args.kind} -- {entry.get('time', '?')}")


def cmd_set_pb(args):
    data = _load(args.file)
    pb = {"time": args.time}
    if args.date:
        pb["date"] = args.date
    if args.event:
        pb["event"] = args.event
    tier_key = "personal_bests" if args.tier == "all_time" else "recent_bests"
    data.setdefault(tier_key, {})[args.distance] = pb
    _save(args.file, data)
    tier_label = "all-time PB" if args.tier == "all_time" else "recent best"
    print(f"Set {args.distance} {tier_label}: {args.time}" + (f" ({args.event}, {args.date})" if args.event else ""))


def cmd_show(args):
    data = _load(args.file)
    print(json.dumps(data, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", default=DEFAULT_PATH, help=f"Path to performance_log.json (default: {DEFAULT_PATH})")
    sub = parser.add_subparsers(dest="command", required=True)

    def common_entry_args(p):
        p.add_argument("--date", required=True, help="YYYY-MM-DD (or YYYY-MM if the exact day isn't known)")
        p.add_argument("--distance-km", type=float, default=None)
        p.add_argument("--time", required=True, help="e.g. 57:56 or 1:59:23")
        p.add_argument("--pace", default=None, help="e.g. 5:48/km")
        p.add_argument("--avg-hr", type=int, default=None)
        p.add_argument("--max-hr", type=int, default=None)
        p.add_argument("--notes", default=None)

    p_race = sub.add_parser("add-race", help="Add a race entry")
    p_race.add_argument("--event", required=True)
    common_entry_args(p_race)
    p_race.set_defaults(func=cmd_add_race)

    p_test = sub.add_parser("add-test", help="Add a controlled test entry (e.g. a 5K time trial)")
    p_test.add_argument("--kind", required=True, help='e.g. "5K test", "threshold test"')
    p_test.add_argument("--event", default=None, help="Optional label; defaults to --kind if omitted")
    common_entry_args(p_test)
    p_test.set_defaults(func=cmd_add_test)

    p_pb = sub.add_parser("set-pb", help="Set/update a personal best or recent-era best")
    p_pb.add_argument("--distance", required=True, help='e.g. "5k", "10k", "half_marathon", "marathon"')
    p_pb.add_argument("--time", required=True)
    p_pb.add_argument("--date", default=None)
    p_pb.add_argument("--event", default=None)
    p_pb.add_argument("--tier", choices=("all_time", "recent"), default="all_time",
                       help="all_time = personal_bests (lifetime PB), recent = recent_bests (current training-era best). Default: all_time")
    p_pb.set_defaults(func=cmd_set_pb)

    p_show = sub.add_parser("show", help="Print the current file contents")
    p_show.set_defaults(func=cmd_show)

    args = parser.parse_args()
    if getattr(args, "command", None) in ("add-race", "add-test") and not getattr(args, "event", None):
        args.event = args.kind if args.command == "add-test" else None
    args.func(args)


if __name__ == "__main__":
    main()

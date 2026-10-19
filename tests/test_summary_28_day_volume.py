from render_summary_md import _four_week_lines


def test_four_week_lines_renders_running_volume_and_average():
    payload = {
        "training_history": {
            "28_day": {
                "avg_weekly_running_distance": 36.9,
                "weekly_total_endurance": [
                    {
                        "week_start": "2026-09-22",
                        "week_end": "2026-09-28",
                        "total_endurance": {"exercise_load": 349.3},
                        "sports": {
                            "running": {"distance": 32.2},
                            "other": {"duration_hours": 0.3},
                        },
                    },
                    {
                        "week_start": "2026-09-29",
                        "week_end": "2026-10-05",
                        "total_endurance": {"exercise_load": 544.5},
                        "sports": {
                            "running": {"distance": 37.14},
                            "other": {"duration_hours": 0.76},
                        },
                    },
                ],
            }
        }
    }

    rendered = "\n".join(_four_week_lines(payload))

    assert "Average weekly running: 36.9 km" in rendered
    assert "| Sep 22–28 | 32.20 km | 18 min | 349.3 |" in rendered
    assert "| Sep 29–Oct 5 | 37.14 km | 46 min | 544.5 |" in rendered


def test_four_week_lines_omits_section_when_28_day_data_missing():
    assert _four_week_lines({}) == []
    assert _four_week_lines({"training_history": {"28_day": {}}}) == []

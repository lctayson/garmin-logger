import json

from generate_ai_analysis import _build_prompt, _main_set_summary


def _activity():
    columns = ["step_type", "time", "avg_pace", "avg_hr", "workout_step_index"]
    rows = [
        ["ACTIVE", "0:20", "4:51", 144, 1],
        ["ACTIVE", "0:20", "4:35", 130, 1],
        ["ACTIVE", "3:00", "5:08", 152, 5],
        ["ACTIVE", "3:00", "5:09", 159, 5],
        ["ACTIVE", "3:00", "5:08", 163, 5],
        ["ACTIVE", "3:00", "5:05", 164, 5],
        ["ACTIVE", "3:00", "5:01", 168, 5],
    ]
    return {
        "name": "5 x 3min VO2 intervals",
        "type": "running",
        "avg_pace": "6:46",
        "splits": {"columns": columns, "data": rows},
    }


def test_main_set_uses_longest_work_rep_group_not_strides():
    result = _main_set_summary(_activity())

    assert result["work_reps"] == 5
    assert result["rep_duration"] == "3:00"
    assert result["rep_paces"] == ["5:08", "5:09", "5:08", "5:05", "5:01"]
    assert result["average_rep_pace"] == "5:06"
    assert result["rep_avg_hr"] == [152, 159, 163, 164, 168]


def test_prompt_includes_rep_data_without_copying_all_splits():
    prompt = json.loads(_build_prompt(_activity(), {"readiness": {"score": 72}}))

    assert prompt["activity"]["avg_pace"] == "6:46"
    assert prompt["activity"]["main_set"]["average_rep_pace"] == "5:06"
    assert "splits" not in prompt["activity"]
    assert prompt["readiness_that_day"]["score"] == 72


def test_system_prompt_defines_interval_drift_and_overall_pace_correctly():
    import generate_ai_analysis

    assert "not the percentage by which the rep pace missed its target" in generate_ai_analysis.SYSTEM_PREFIX
    assert "not from whole-activity average pace" in generate_ai_analysis.SYSTEM_PREFIX

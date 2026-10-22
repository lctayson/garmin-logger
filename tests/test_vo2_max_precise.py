from compact_metrics import compact_metrics
from render_summary_md import _readiness_lines


def test_precise_vo2_max_is_preserved_and_moved_to_readiness_head():
    payload = {
        "date": "2026-10-22",
        "daily_readiness": {"readiness": {"score": 80, "level": "Good"}},
        "health_stats": {},
        "training_status": {
            "status": "Maintaining",
            "vo2_max": {"value": 45, "precise_value": 45.37, "status": "Excellent"},
        },
    }

    result = compact_metrics(payload)

    assert result["vo2_max"] == 45
    assert result["vo2_max_precise"] == 45.37
    assert list(result["readiness"])[:2] == ["vo2_max", "vo2_max_precise"]
    assert result["readiness"]["vo2_max_precise"] == 45.37


def test_readiness_summary_shows_precise_vo2_max_before_recovery_metrics():
    payload = {
        "readiness": {
            "vo2_max": 45,
            "vo2_max_precise": 45.37,
            "resting_hr": 60,
        }
    }

    lines = _readiness_lines(payload, {"readiness": {}})

    assert lines.index("- **VO₂max:** 45.37 ml/kg/min (Garmin precise)") < next(
        i for i, line in enumerate(lines) if "**RHR:**" in line
    )


def test_readiness_summary_labels_missing_precise_vo2_max():
    lines = _readiness_lines({"vo2_max": 45, "readiness": {}}, {"readiness": {}})
    assert "- **VO₂max:** 45 ml/kg/min (precise value unavailable)" in lines

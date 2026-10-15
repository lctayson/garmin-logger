from metrics_summary import build_summary
from render_summary_md import _readiness_lines


def test_readiness_quick_reference_shows_hrv_band_sleep_need_and_recovery():
    metrics = {
        "date": "2026-10-15",
        "readiness": {
            "score": 63,
            "level": "Moderate",
            "feedback": "Balance Stress And Recovery",
            "resting_hr": 57,
            "hrv_last_night_avg_ms": 54,
            "hrv_7_day_avg_ms": 49,
            "sleep_hours": 5.87,
            "sleep_score": 75,
            "recovery_hours": 0,
            "hrv_baseline": {"balancedLow": 47, "balancedUpper": 57},
        },
        "sleep": {"need_h": 7.0},
        "trend_recent_daily": {
            "columns": ["resting_hr", "hrv_last_night_avg_ms", "sleep_hours"],
            "data": [
                [57, 48, 5.5],
                [59, 46, 5.57],
                [59, 46, 5.52],
                [59, 48, 7.45],
                [55, 56, 7.1],
                [59, 46, 6.53],
                [57, 54, 5.87],
            ],
        },
    }

    lines = _readiness_lines(metrics, build_summary(metrics))
    rendered = "\n".join(lines)

    assert "RHR:** 57 bpm" in rendered
    assert "HRV:** 54ms" in rendered
    assert "balanced range: 47–57ms" in rendered
    assert "Sleep:** 5h52 / 7h00 need (1h08 short)" in rendered
    assert "score 75" in rendered
    assert "7d avg 6h13" in rendered
    assert "nights below need" in rendered
    assert "Recovery remaining:** 0h00" in rendered

from datetime import date

import render_summary_md


def test_live_sheet_session_uses_column_b_week_start_and_hidden_m_flag(monkeypatch):
    # A published CSV includes hidden column M even though the spreadsheet UI
    # hides it. B is the Monday week-start date; C:I are Monday through Sunday.
    rows = [
        ["Week", "Week Start", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "", "", "", "Current Week"],
        ["W4", "12 Oct", "Strength A", "SUT 3x8min", "EZ + strides", "4x1k VO2", "REST + Core", "12K EZ", "7k EZ @ 6:50–7:20 ≤150bpm w/ 6–8x10s hills", "", "", "", "TRUE"],
    ]
    monkeypatch.setattr(render_summary_md, "_fetch_training_plan_rows", lambda url: rows)

    session = render_summary_md._planned_session_from_sheet(
        date(2026, 10, 18), render_summary_md.TRAINING_PLAN_URL
    )

    assert session == "7k EZ @ 6:50–7:20 ≤150bpm w/ 6–8x10s hills"


def test_planned_session_falls_back_to_live_sheet_when_context_only_links_sheet(monkeypatch):
    monkeypatch.setattr(
        render_summary_md,
        "_planned_session_from_sheet",
        lambda target_day, sheet_url: "6k recovery with 6-8x10s hills",
    )
    context = """# BHM 2027 Training Plan

Source of truth: the updated BHM 2027 Plan spreadsheet.

> [Open Live BHM 2027 Training Plan (Google Sheets)](https://docs.google.com/spreadsheets/d/e/example/pubhtml?gid=810767784&single=true)
"""

    session = render_summary_md._planned_session(
        context, date(2026, 10, 18), "# BHM 2027 Training Plan"
    )

    assert session == "6k recovery with 6-8x10s hills"

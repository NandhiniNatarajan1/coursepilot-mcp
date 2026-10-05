"""Unit tests for sync orchestrator deduplication logic."""
from __future__ import annotations

from datetime import datetime

from shared.models import AcademicEvent, EventSource, EventType
from sync_orchestrator import deduplicate, format_title, format_description


def _event(**kwargs) -> AcademicEvent:
    defaults = dict(
        course="CS 3200",
        title="Homework 4",
        event_type=EventType.HOMEWORK,
        due_datetime=datetime(2026, 10, 14, 23, 59),
        source=EventSource.CANVAS_ASSIGNMENT,
    )
    defaults.update(kwargs)
    return AcademicEvent(**defaults)


def test_dedup_collapses_identical_events():
    events = [_event(), _event()]
    result = deduplicate(events)
    assert len(result) == 1


def test_dedup_prefers_canvas_assignment_over_syllabus():
    syllabus = _event(source=EventSource.CANVAS_SYLLABUS, title="HW 4")
    assignment = _event(source=EventSource.CANVAS_ASSIGNMENT, title="Homework 4")
    result = deduplicate([syllabus, assignment])
    assert len(result) == 1
    assert result[0].source == EventSource.CANVAS_ASSIGNMENT


def test_dedup_prefers_canvas_assignment_regardless_of_insertion_order():
    assignment = _event(source=EventSource.CANVAS_ASSIGNMENT, title="Homework 4")
    syllabus = _event(source=EventSource.CANVAS_SYLLABUS, title="HW 4")
    # Insert syllabus FIRST — assignment should still win.
    result = deduplicate([assignment, syllabus])
    assert len(result) == 1
    assert result[0].source == EventSource.CANVAS_ASSIGNMENT


def test_dedup_keeps_distinct_events():
    a = _event(title="Homework 4", due_datetime=datetime(2026, 10, 14))
    b = _event(title="Homework 5", due_datetime=datetime(2026, 10, 21))
    assert len(deduplicate([a, b])) == 2


def test_dedup_treats_different_courses_as_distinct():
    a = _event(course="CS 3200", title="Midterm")
    b = _event(course="FINA 4335", title="Midterm")
    assert len(deduplicate([a, b])) == 2


def test_format_title_uses_em_dash():
    e = _event(course="CS 3200", title="Homework 4")
    assert format_title(e) == "CS 3200 — Homework 4"


def test_format_description_includes_course_type_source():
    e = _event()
    desc = format_description(e)
    assert "Course: CS 3200" in desc
    assert "Type: homework" in desc
    assert "Source: canvas_assignment" in desc

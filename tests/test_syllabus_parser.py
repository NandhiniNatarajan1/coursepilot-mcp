"""Unit tests for the syllabus parser.

These do not hit the network or require a Canvas token.
"""
from __future__ import annotations

from canvas_server.syllabus_parser import parse_syllabus
from shared.models import EventType


def test_empty_syllabus_returns_empty_list():
    assert parse_syllabus("", "CS 3200") == []


def test_syllabus_with_no_dates_returns_empty():
    text = "Welcome to CS 3200. Office hours are Mondays."
    assert parse_syllabus(text, "CS 3200") == []


def test_extracts_midterm_exam_date():
    text = "Midterm Exam: October 22"
    events = parse_syllabus(text, "CS 3200", default_year=2026)
    assert len(events) == 1
    e = events[0]
    assert e.course == "CS 3200"
    assert e.event_type == EventType.MIDTERM
    assert e.due_datetime.month == 10
    assert e.due_datetime.day == 22


def test_extracts_final_exam_with_time():
    text = "Final Exam: December 15 at 8:00 AM"
    events = parse_syllabus(text, "CS 3200", default_year=2026)
    assert len(events) == 1
    e = events[0]
    assert e.event_type == EventType.FINAL
    assert e.due_datetime.month == 12
    assert e.due_datetime.day == 15
    assert e.due_datetime.hour == 8


def test_extracts_multiple_events():
    text = """
    Midterm Exam: October 22
    Exam 2: November 19
    Final Exam: December 15
    Project Presentation: November 30
    Homework 5 due October 14
    """
    events = parse_syllabus(text, "CS 3200", default_year=2026)
    types = {e.event_type for e in events}
    assert EventType.MIDTERM in types
    assert EventType.EXAM in types
    assert EventType.FINAL in types
    assert EventType.PRESENTATION in types or EventType.PROJECT in types
    assert EventType.HOMEWORK in types


def test_ignores_vague_dates():
    text = "Final Exam: See university final exam schedule"
    assert parse_syllabus(text, "CS 3200") == []


def test_ignores_tbd():
    text = "Project 3: TBD"
    assert parse_syllabus(text, "CS 3200") == []


def test_handles_numeric_dates():
    text = "Homework 4 due 10/14/2026"
    events = parse_syllabus(text, "CS 3200")
    assert len(events) == 1
    e = events[0]
    assert e.event_type == EventType.HOMEWORK
    assert e.due_datetime.year == 2026
    assert e.due_datetime.month == 10
    assert e.due_datetime.day == 14


def test_handles_abbreviated_month():
    text = "Quiz 3: Oct 22, 2026"
    events = parse_syllabus(text, "CS 3200")
    assert len(events) == 1
    assert events[0].event_type == EventType.QUIZ


def test_handles_html_tables():
    html = """
    <table>
      <tr><td>Midterm Exam</td><td>October 22, 2026</td></tr>
      <tr><td>Final Exam</td><td>December 15, 2026</td></tr>
    </table>
    """
    events = parse_syllabus(html, "CS 3200")
    types = {e.event_type for e in events}
    assert EventType.MIDTERM in types
    assert EventType.FINAL in types


def test_hw_abbreviation_normalized_in_dedup():
    text = """
    HW 4 due October 14, 2026
    Homework 4 due October 14, 2026
    """
    events = parse_syllabus(text, "CS 3200")
    # Both lines point at the same event; dedup should collapse them.
    assert len(events) == 1


def test_long_line_is_skipped():
    text = "exam " + ("blah " * 200) + "October 22"
    assert parse_syllabus(text, "CS 3200") == []

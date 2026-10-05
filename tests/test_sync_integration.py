"""Integration tests for sync_orchestrator.

These do NOT spawn real MCP servers — they mock the ClientSession so we can
exercise the orchestration logic (collect, dedup, create/update) deterministically.
"""
from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from shared.models import AcademicEvent, EventSource, EventType
from sync_orchestrator import (
    _needs_update,
    collect_canvas_events,
    sync_events,
)


def _mcp_result(payload) -> SimpleNamespace:
    """Build a fake MCP tool-call result wrapping JSON text content."""
    content = [SimpleNamespace(text=json.dumps(payload))]
    return SimpleNamespace(content=content)


def _mock_canvas_session(courses, assignments_by_course, syllabus_by_course):
    session = AsyncMock()

    async def call_tool(name, arguments=None):
        arguments = arguments or {}
        if name == "canvas_get_courses":
            return _mcp_result(courses)
        if name == "canvas_get_assignments":
            cid = arguments["course_id"]
            return _mcp_result(assignments_by_course.get(cid, []))
        if name == "canvas_get_syllabus":
            cid = arguments["course_id"]
            return _mcp_result(syllabus_by_course.get(cid, {"events": []}))
        raise AssertionError(f"unexpected tool: {name}")

    session.call_tool = AsyncMock(side_effect=call_tool)
    return session


@pytest.mark.asyncio
async def test_collect_canvas_events_pulls_assignments_and_syllabus(monkeypatch):
    # Isolate from a user's local .env that may set TERM_FILTER.
    monkeypatch.setattr("sync_orchestrator.config.TERM_FILTER", [])

    courses = [
        {"course_id": 1, "course_name": "Database Design", "course_code": "CS 3200"},
    ]
    assignment_payload = AcademicEvent(
        course="CS 3200",
        title="Homework 4",
        event_type=EventType.HOMEWORK,
        due_datetime=datetime(2026, 10, 14, 23, 59),
        source=EventSource.CANVAS_ASSIGNMENT,
        source_id="canvas_assignment_1",
    ).model_dump(mode="json")

    syllabus_event = AcademicEvent(
        course="CS 3200",
        title="Midterm Exam",
        event_type=EventType.MIDTERM,
        due_datetime=datetime(2026, 10, 22, 0, 0),
        source=EventSource.CANVAS_SYLLABUS,
    ).model_dump(mode="json")

    session = _mock_canvas_session(
        courses=courses,
        assignments_by_course={1: [assignment_payload]},
        syllabus_by_course={1: {"events": [syllabus_event]}},
    )

    events = await collect_canvas_events(session)
    titles = {e.title for e in events}
    assert titles == {"Homework 4", "Midterm Exam"}


@pytest.mark.asyncio
async def test_sync_creates_new_events_when_none_exist():
    session = AsyncMock()

    async def call_tool(name, arguments=None):
        if name == "calendar_find_event":
            return _mcp_result([])  # no matches found
        if name == "calendar_create_event":
            return _mcp_result({"event_id": "evt_123", "title": arguments["title"]})
        raise AssertionError(f"unexpected tool: {name}")

    session.call_tool = AsyncMock(side_effect=call_tool)

    events = [
        AcademicEvent(
            course="CS 3200",
            title="Homework 4",
            event_type=EventType.HOMEWORK,
            due_datetime=datetime(2026, 10, 14, 23, 59),
            source=EventSource.CANVAS_ASSIGNMENT,
        )
    ]
    summary = await sync_events(events, session)
    assert summary == {"created": 1, "updated": 0, "skipped": 0, "failed": 0}


@pytest.mark.asyncio
async def test_sync_skips_matching_events():
    due = datetime(2026, 10, 14, 23, 59)
    session = AsyncMock()

    async def call_tool(name, arguments=None):
        if name == "calendar_find_event":
            return _mcp_result(
                [
                    {
                        "event_id": "evt_existing",
                        "title": "CS 3200 — Homework 4",
                        "start": due.isoformat(),
                    }
                ]
            )
        raise AssertionError(f"unexpected tool: {name}")

    session.call_tool = AsyncMock(side_effect=call_tool)

    events = [
        AcademicEvent(
            course="CS 3200",
            title="Homework 4",
            event_type=EventType.HOMEWORK,
            due_datetime=due,
            source=EventSource.CANVAS_ASSIGNMENT,
        )
    ]
    summary = await sync_events(events, session)
    assert summary == {"created": 0, "updated": 0, "skipped": 1, "failed": 0}


@pytest.mark.asyncio
async def test_sync_updates_events_when_date_differs():
    old_due = datetime(2026, 10, 14, 23, 59)
    new_due = datetime(2026, 10, 16, 23, 59)
    session = AsyncMock()
    call_log: list[tuple[str, dict]] = []

    async def call_tool(name, arguments=None):
        call_log.append((name, arguments or {}))
        if name == "calendar_find_event":
            return _mcp_result(
                [
                    {
                        "event_id": "evt_existing",
                        "title": "CS 3200 — Homework 4",
                        "start": old_due.isoformat(),
                    }
                ]
            )
        if name == "calendar_update_event":
            return _mcp_result(
                {"event_id": arguments["event_id"], "updated": True, "updated_fields": ["start"]}
            )
        raise AssertionError(f"unexpected tool: {name}")

    session.call_tool = AsyncMock(side_effect=call_tool)

    events = [
        AcademicEvent(
            course="CS 3200",
            title="Homework 4",
            event_type=EventType.HOMEWORK,
            due_datetime=new_due,
            source=EventSource.CANVAS_ASSIGNMENT,
        )
    ]
    summary = await sync_events(events, session)
    assert summary == {"created": 0, "updated": 1, "skipped": 0, "failed": 0}
    update_call = next(c for c in call_log if c[0] == "calendar_update_event")
    assert update_call[1]["event_id"] == "evt_existing"
    assert update_call[1]["start_datetime"] == new_due.isoformat()


def test_needs_update_detects_date_change():
    existing = {"start": "2026-10-14T23:59:00"}
    assert _needs_update(existing, datetime(2026, 10, 16, 23, 59)) is True
    assert _needs_update(existing, datetime(2026, 10, 14, 23, 59)) is False


def test_needs_update_tolerates_minor_time_drift():
    existing = {"start": "2026-10-14T23:59:00"}
    # 30 seconds off should be considered equivalent.
    assert _needs_update(existing, datetime(2026, 10, 14, 23, 59, 30)) is False

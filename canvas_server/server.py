"""Canvas MCP server.

Exposes three tools backed by the Canvas REST API:
    - canvas_get_courses()
    - canvas_get_assignments(course_id)
    - canvas_get_syllabus(course_id)

Run with:
    python -m canvas_server.server
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Allow running as `python canvas_server/server.py` from project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.mcpserver import MCPServer

import config
from canvas_server.canvas_api import CanvasAPI, CanvasAPIError
from canvas_server.syllabus_parser import parse_syllabus
from shared.models import AcademicEvent, EventSource, EventType

logging.basicConfig(level=config.LOG_LEVEL)
logger = logging.getLogger(__name__)

mcp = MCPServer(name="canvas", version="0.1.0")


def _api() -> CanvasAPI:
    return CanvasAPI(config.CANVAS_API_TOKEN, config.CANVAS_BASE_URL)


@mcp.tool()
def canvas_get_courses() -> list[dict]:
    """List the student's active Canvas courses.

    Returns a list of {course_id, course_name, course_code}.
    """
    try:
        return _api().get_courses()
    except CanvasAPIError as e:
        logger.exception("get_courses failed")
        return [{"error": str(e)}]


@mcp.tool()
def canvas_get_assignments(course_id: int, course_code: str = "") -> list[dict]:
    """List assignments for a Canvas course as AcademicEvent dicts.

    Args:
        course_id: Canvas course id.
        course_code: Short course code (e.g. "CS 3200") to attach to events.
            If omitted, the course_id is used as a fallback label.
    """
    label = course_code or f"canvas_course_{course_id}"
    try:
        raw = _api().get_assignments(course_id)
    except CanvasAPIError as e:
        logger.exception("get_assignments failed for course %s", course_id)
        return [{"error": str(e)}]

    events: list[AcademicEvent] = []
    for item in raw:
        if not item.get("due_at"):
            continue
        from datetime import datetime

        due = datetime.fromisoformat(item["due_at"].replace("Z", "+00:00"))
        events.append(
            AcademicEvent(
                course=label,
                title=item["name"],
                event_type=_guess_type(item["name"]),
                due_datetime=due,
                source=EventSource.CANVAS_ASSIGNMENT,
                source_id=f"canvas_assignment_{item['assignment_id']}",
            )
        )
    return [e.model_dump(mode="json") for e in events]


@mcp.tool()
def canvas_get_syllabus(course_id: int, course_code: str = "") -> dict:
    """Fetch and parse a course syllabus.

    Returns {course_id, course_name, events} where events are AcademicEvent
    dicts extracted from the syllabus text.
    """
    label = course_code or f"canvas_course_{course_id}"
    try:
        data = _api().get_syllabus(course_id)
    except CanvasAPIError as e:
        logger.exception("get_syllabus failed for course %s", course_id)
        return {"course_id": course_id, "error": str(e), "events": []}

    events = parse_syllabus(data["syllabus_html"], course_code=label)
    return {
        "course_id": course_id,
        "course_name": data["course_name"],
        "events": [e.model_dump(mode="json") for e in events],
    }


def _guess_type(title: str) -> EventType:
    """Best-effort event type from an assignment title."""
    low = title.lower()
    if "midterm" in low:
        return EventType.MIDTERM
    if "final" in low:
        return EventType.FINAL
    if "exam" in low:
        return EventType.EXAM
    if "quiz" in low:
        return EventType.QUIZ
    if "project" in low:
        return EventType.PROJECT
    if "lab" in low:
        return EventType.LAB
    if "paper" in low or "essay" in low:
        return EventType.PAPER
    if "presentation" in low:
        return EventType.PRESENTATION
    if "homework" in low or "hw" in low.split():
        return EventType.HOMEWORK
    return EventType.ASSIGNMENT


if __name__ == "__main__":
    missing = config.validate()
    if missing:
        logger.warning("Missing config: %s", missing)
    mcp.run()

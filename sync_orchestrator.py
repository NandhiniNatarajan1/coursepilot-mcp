"""Sync orchestrator — the MCP client that ties the two servers together.

Flow:
    1. Spawn the Canvas MCP server as a subprocess.
    2. Spawn the Google Calendar MCP server as a subprocess.
    3. Open an MCP client session against each.
    4. Pull courses → assignments + syllabus events from Canvas.
    5. Deduplicate (Canvas assignments win over syllabus).
    6. For each event, find-or-create-or-update the Google Calendar event.

This is the "aha" moment: both servers are black boxes behind the MCP
protocol. The orchestrator never imports from canvas_api or google_api — it
only speaks MCP tool calls.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime, timedelta
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import config
from shared.models import AcademicEvent, EventSource

logging.basicConfig(
    level=config.LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sync")

# Event source priority (lower index = higher priority).
SOURCE_PRIORITY = {
    EventSource.CANVAS_ASSIGNMENT: 0,
    EventSource.CANVAS_CALENDAR: 1,
    EventSource.CANVAS_SYLLABUS: 2,
    EventSource.CANVAS_ANNOUNCEMENT: 3,
}


# ---------- MCP helpers ----------

async def _call(session: ClientSession, name: str, arguments: dict | None = None) -> Any:
    """Call a tool and unwrap the JSON payload."""
    result = await session.call_tool(name, arguments=arguments or {})
    # MCP tool results arrive as a list of content items; our tools return
    # JSON-serializable structures as text content.
    for item in result.content:
        text = getattr(item, "text", None)
        if text is None:
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return None


def _canvas_params() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "canvas_server.server"],
    )


def _calendar_params() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "google_calendar_server.server"],
    )


# ---------- Event collection ----------

async def collect_canvas_events(canvas: ClientSession) -> list[AcademicEvent]:
    """Gather assignments + syllabus events from every active course.

    If config.TERM_FILTER is set, only courses whose course_code contains one
    of the configured substrings are included.
    """
    courses = await _call(canvas, "canvas_get_courses")
    if not courses or (isinstance(courses, list) and courses and "error" in courses[0]):
        logger.error("Could not fetch courses: %s", courses)
        return []

    if config.TERM_FILTER:
        courses = [
            c for c in courses
            if any(term in c.get("course_code", "") for term in config.TERM_FILTER)
        ]
        logger.info("Filtered to %d courses matching TERM_FILTER=%s",
                    len(courses), config.TERM_FILTER)

    all_events: list[AcademicEvent] = []
    for course in courses:
        code = course["course_code"]
        cid = course["course_id"]
        logger.info("Fetching course %s (%s)", code, cid)

        assignments = await _call(
            canvas, "canvas_get_assignments", {"course_id": cid, "course_code": code}
        )
        syllabus = await _call(
            canvas, "canvas_get_syllabus", {"course_id": cid, "course_code": code}
        )

        for raw in assignments or []:
            if "error" in raw:
                logger.warning("Assignment error for %s: %s", code, raw["error"])
                continue
            all_events.append(AcademicEvent(**raw))

        for raw in (syllabus or {}).get("events", []):
            all_events.append(AcademicEvent(**raw))

    logger.info("Collected %d raw events across %d courses", len(all_events), len(courses))
    return all_events


# ---------- Dedup ----------

def deduplicate(events: list[AcademicEvent]) -> list[AcademicEvent]:
    """Keep the highest-priority event for each dedup key."""
    best: dict[tuple[str, str, str], AcademicEvent] = {}
    for e in events:
        key = e.dedup_key()
        current = best.get(key)
        if current is None or SOURCE_PRIORITY[e.source] < SOURCE_PRIORITY[current.source]:
            best[key] = e
    deduped = list(best.values())
    logger.info("Deduplicated %d -> %d events", len(events), len(deduped))
    return deduped


# ---------- Calendar sync ----------

def format_title(event: AcademicEvent) -> str:
    return f"{event.course} — {event.title}"


def format_description(event: AcademicEvent) -> str:
    lines = [
        f"Course: {event.course}",
        f"Type: {event.event_type.value}",
        f"Source: {event.source.value}",
    ]
    if event.source_id:
        lines.append(f"Source ID: {event.source_id}")
    return "\n".join(lines)


async def sync_events(events: list[AcademicEvent], calendar: ClientSession) -> dict:
    """Create/update calendar events to match the academic events."""
    created = updated = skipped = failed = 0

    for event in events:
        dt = event.due_datetime or event.start_datetime
        if dt is None:
            continue

        title = format_title(event)
        description = format_description(event)
        start_iso = dt.isoformat()

        existing = await _find_match(calendar, title, dt)

        if existing is None:
            result = await _call(
                calendar,
                "calendar_create_event",
                {"title": title, "start_datetime": start_iso, "description": description},
            )
            if isinstance(result, dict) and "error" in result:
                logger.error("Create failed for %s: %s", title, result["error"])
                failed += 1
            else:
                logger.info("Created: %s @ %s", title, start_iso)
                created += 1
        elif _needs_update(existing, dt):
            result = await _call(
                calendar,
                "calendar_update_event",
                {
                    "event_id": existing["event_id"],
                    "start_datetime": start_iso,
                    "description": description,
                },
            )
            if isinstance(result, dict) and result.get("error"):
                logger.error("Update failed for %s: %s", title, result["error"])
                failed += 1
            else:
                logger.info("Updated: %s -> %s", title, start_iso)
                updated += 1
        else:
            skipped += 1

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
    }


async def _find_match(
    calendar: ClientSession, title: str, when: datetime
) -> dict | None:
    """Look for a calendar event with the same title near the same day."""
    time_min = (when - timedelta(days=1)).isoformat()
    time_max = (when + timedelta(days=1)).isoformat()
    matches = await _call(
        calendar,
        "calendar_find_event",
        {"query": title, "time_min": time_min, "time_max": time_max},
    )
    if not matches or (isinstance(matches, list) and matches and "error" in matches[0]):
        return None
    for m in matches:
        if m.get("title", "").strip() == title.strip():
            return m
    return None


def _needs_update(existing: dict, when: datetime) -> bool:
    """Compare existing event start to the target datetime at minute resolution."""
    existing_start = existing.get("start")
    if not existing_start:
        return True
    try:
        existing_dt = datetime.fromisoformat(existing_start.replace("Z", "+00:00"))
    except ValueError:
        return True
    # Normalize: drop tzinfo for comparison since Canvas times are naive.
    e = existing_dt.replace(tzinfo=None)
    t = when.replace(tzinfo=None)
    return abs((e - t).total_seconds()) > 60


# ---------- Entrypoint ----------

async def sync_semester() -> dict:
    """Full sync pipeline. Returns a summary dict."""
    async with stdio_client(_canvas_params()) as (c_read, c_write):
        async with ClientSession(c_read, c_write) as canvas:
            await canvas.initialize()
            events = await collect_canvas_events(canvas)

    if not events:
        logger.warning("No events collected; skipping calendar sync.")
        return {"collected": 0, "created": 0, "updated": 0, "skipped": 0, "failed": 0}

    deduped = deduplicate(events)

    async with stdio_client(_calendar_params()) as (g_read, g_write):
        async with ClientSession(g_read, g_write) as calendar:
            await calendar.initialize()
            summary = await sync_events(deduped, calendar)

    summary["collected"] = len(events)
    summary["deduped"] = len(deduped)
    return summary


def main() -> None:
    missing = config.validate()
    if missing:
        logger.error("Cannot run sync: missing config %s", missing)
        sys.exit(1)
    summary = asyncio.run(sync_semester())
    logger.info("Sync complete: %s", summary)


if __name__ == "__main__":
    main()

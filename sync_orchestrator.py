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
from datetime import datetime, timedelta, timezone
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
    """Call a tool and unwrap the JSON payload.

    MCP serializes a Python `list[...]` return by emitting one TextContent per
    element, so we must accumulate rather than return the first item. For a
    tool that returns a single dict or scalar, there is exactly one content
    item and we unwrap it.
    """
    result = await session.call_tool(name, arguments=arguments or {})
    parsed: list = []
    for item in result.content:
        text = getattr(item, "text", None)
        if text is None:
            continue
        try:
            parsed.append(json.loads(text))
        except json.JSONDecodeError:
            parsed.append(text)
    if not parsed:
        return None
    if len(parsed) == 1:
        return parsed[0]
    return parsed


async def _call_list(session: ClientSession, name: str, arguments: dict | None = None) -> list:
    """Like _call but always returns a list, even for 0 or 1 result items."""
    result = await _call(session, name, arguments)
    if result is None:
        return []
    if isinstance(result, list):
        return result
    return [result]


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


def _short_code(course_code: str) -> str:
    """Trim a Canvas course code to its short, human-readable prefix.

    Canvas serves codes like 'DS4300.13913.202710'; we only want 'DS4300'
    on calendar titles. If the first segment is non-trivial (not just dots),
    return it; otherwise fall back to the original string.
    """
    first = course_code.split(".", 1)[0].strip()
    return first or course_code


# ---------- Event collection ----------

async def collect_canvas_events(canvas: ClientSession) -> list[AcademicEvent]:
    """Gather assignments + syllabus events from every active course.

    If config.TERM_FILTER is set, only courses whose course_code contains one
    of the configured substrings are included.
    """
    courses = await _call_list(canvas, "canvas_get_courses")
    if courses and "error" in courses[0]:
        logger.error("Could not fetch courses: %s", courses[0])
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
        raw_code = course["course_code"]
        code = _short_code(raw_code)
        cid = course["course_id"]
        logger.info("Fetching course %s (%s)", code, cid)

        assignments = await _call_list(
            canvas, "canvas_get_assignments", {"course_id": cid, "course_code": code}
        )
        syllabus = await _call(
            canvas, "canvas_get_syllabus", {"course_id": cid, "course_code": code}
        )

        for raw in assignments:
            if "error" in raw:
                logger.warning("Assignment error for %s: %s", code, raw["error"])
                continue
            all_events.append(AcademicEvent(**raw))

        syllabus_events = (syllabus or {}).get("events", []) if isinstance(syllabus, dict) else []
        for raw in syllabus_events:
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
    matches = await _call_list(
        calendar,
        "calendar_find_event",
        {"query": title, "time_min": time_min, "time_max": time_max},
    )
    if matches and "error" in matches[0]:
        return None
    for m in matches:
        if m.get("title", "").strip() == title.strip():
            return m
    return None


def _needs_update(existing: dict, when: datetime) -> bool:
    """Compare existing event start to the target datetime at minute resolution.

    Google returns start times in the event's display timezone (e.g. the
    America/New_York offset), while Canvas gives us UTC. Normalize both to
    UTC before comparing so we do not re-update unchanged events on every run.
    """
    existing_start = existing.get("start")
    if not existing_start:
        return True
    try:
        existing_dt = datetime.fromisoformat(existing_start.replace("Z", "+00:00"))
    except ValueError:
        return True
    if existing_dt.tzinfo is None:
        existing_dt = existing_dt.replace(tzinfo=timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return abs((existing_dt - when).total_seconds()) > 60


# ---------- Cleanup ----------

CLEANUP_MARKER = "Source: canvas_"


async def cleanup_synced_events(days_back: int = 180, days_ahead: int = 365) -> dict:
    """Delete every calendar event this app previously created.

    Identified by the marker string this orchestrator writes into every
    event's description ('Source: canvas_...'). Searches a wide window
    (default: 180 days back, 365 days ahead) so past-dated events are
    caught too. Safe to run even when nothing was created yet.
    """
    now = datetime.utcnow()
    time_min = (now - timedelta(days=days_back)).isoformat()
    time_max = (now + timedelta(days=days_ahead)).isoformat()

    deleted = failed = scanned = 0
    async with stdio_client(_calendar_params()) as (g_read, g_write):
        async with ClientSession(g_read, g_write) as calendar:
            await calendar.initialize()
            events = await _call_list(
                calendar,
                "calendar_find_event",
                {"query": "", "time_min": time_min, "time_max": time_max},
            )
            for e in events:
                scanned += 1
                if "error" in e:
                    continue
                if CLEANUP_MARKER not in (e.get("description") or ""):
                    continue
                result = await _call(
                    calendar, "calendar_delete_event", {"event_id": e["event_id"]}
                )
                if isinstance(result, dict) and result.get("deleted"):
                    logger.info("Deleted: %s", e.get("title"))
                    deleted += 1
                else:
                    logger.error("Delete failed for %s: %s", e.get("title"), result)
                    failed += 1
    return {"scanned": scanned, "deleted": deleted, "failed": failed}


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
    if "--cleanup" in sys.argv:
        summary = asyncio.run(cleanup_synced_events())
        logger.info("Cleanup complete: %s", summary)
        return
    summary = asyncio.run(sync_semester())
    logger.info("Sync complete: %s", summary)


if __name__ == "__main__":
    main()

"""Google Calendar MCP server.

Exposes four tools:
    - calendar_create_event
    - calendar_update_event
    - calendar_find_event
    - calendar_list_upcoming

Run with:
    python -m google_calendar_server.server
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.mcpserver import MCPServer

import config
from google_calendar_server.google_api import GoogleCalendarAPI, GoogleCalendarError

logging.basicConfig(level=config.LOG_LEVEL)
logger = logging.getLogger(__name__)

mcp = MCPServer(name="google-calendar", version="0.1.0")

_api_instance: GoogleCalendarAPI | None = None


def _api() -> GoogleCalendarAPI:
    """Lazy singleton — the OAuth flow only runs once per process."""
    global _api_instance
    if _api_instance is None:
        _api_instance = GoogleCalendarAPI(
            credentials_path=config.GOOGLE_CREDENTIALS_JSON,
            token_path=config.GOOGLE_TOKEN_JSON,
            scopes=config.GOOGLE_CALENDAR_SCOPES,
        )
    return _api_instance


def _parse_dt(value: str) -> datetime:
    """Accept ISO 8601 strings; raise ValueError otherwise."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@mcp.tool()
def calendar_create_event(
    title: str,
    start_datetime: str,
    end_datetime: str = "",
    description: str = "",
) -> dict:
    """Create a Google Calendar event.

    Args:
        title: Event summary, e.g. "CS 3200 — Homework 4".
        start_datetime: ISO 8601 start time (e.g. "2026-10-14T23:59:00").
        end_datetime: ISO 8601 end time. Defaults to start + 1 hour.
        description: Longer description shown on the event.
    """
    try:
        start = _parse_dt(start_datetime)
        end = _parse_dt(end_datetime) if end_datetime else None
        return _api().create_event(title=title, start=start, end=end, description=description)
    except (GoogleCalendarError, ValueError) as e:
        logger.exception("create_event failed")
        return {"error": str(e)}


@mcp.tool()
def calendar_update_event(
    event_id: str,
    title: str = "",
    start_datetime: str = "",
    end_datetime: str = "",
    description: str = "",
) -> dict:
    """Patch an existing Google Calendar event. Empty args are ignored.

    Args:
        event_id: ID returned by create_event or find_event.
        title: New summary (optional).
        start_datetime: New ISO start time (optional).
        end_datetime: New ISO end time (optional).
        description: New description (optional).
    """
    try:
        return _api().update_event(
            event_id=event_id,
            title=title or None,
            start=_parse_dt(start_datetime) if start_datetime else None,
            end=_parse_dt(end_datetime) if end_datetime else None,
            description=description or None,
        )
    except (GoogleCalendarError, ValueError) as e:
        logger.exception("update_event failed")
        return {"error": str(e)}


@mcp.tool()
def calendar_find_event(
    query: str,
    time_min: str = "",
    time_max: str = "",
) -> list[dict]:
    """Search calendar events by text query within an optional time range.

    Args:
        query: Free-text search (matches summary/description).
        time_min: ISO lower bound (optional).
        time_max: ISO upper bound (optional).
    """
    try:
        return _api().find_event(
            query=query,
            time_min=_parse_dt(time_min) if time_min else None,
            time_max=_parse_dt(time_max) if time_max else None,
        )
    except (GoogleCalendarError, ValueError) as e:
        logger.exception("find_event failed")
        return [{"error": str(e)}]


@mcp.tool()
def calendar_delete_event(event_id: str) -> dict:
    """Delete a Google Calendar event by id."""
    try:
        return _api().delete_event(event_id)
    except GoogleCalendarError as e:
        logger.exception("delete_event failed")
        return {"error": str(e)}


@mcp.tool()
def calendar_list_upcoming(days_ahead: int = 90) -> list[dict]:
    """List events in the next N days. Useful for sync comparison."""
    try:
        return _api().list_upcoming(days_ahead=days_ahead)
    except GoogleCalendarError as e:
        logger.exception("list_upcoming failed")
        return [{"error": str(e)}]


if __name__ == "__main__":
    missing = config.validate()
    if missing:
        logger.warning("Missing config: %s", missing)
    mcp.run()

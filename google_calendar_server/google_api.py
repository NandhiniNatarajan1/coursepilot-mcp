"""Google Calendar API wrapper.

First run opens a browser for OAuth consent and writes a token.json next to
credentials.json. Subsequent runs reuse the stored token (and silently
refresh when it expires).

Prerequisites:
    - A Google Cloud project with the Calendar API enabled.
    - An OAuth client of type "Desktop" with its credentials.json downloaded.
    - config.GOOGLE_CREDENTIALS_JSON points at that credentials.json.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


class GoogleCalendarError(Exception):
    pass


class GoogleCalendarAPI:
    def __init__(
        self,
        credentials_path: str,
        token_path: str,
        scopes: list[str],
        calendar_id: str = "primary",
    ):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.scopes = scopes
        self.calendar_id = calendar_id
        self.service = build("calendar", "v3", credentials=self._auth())

    def _auth(self) -> Credentials:
        creds: Credentials | None = None
        token_file = Path(self.token_path)
        if token_file.exists():
            creds = Credentials.from_authorized_user_file(self.token_path, self.scopes)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not Path(self.credentials_path).exists():
                    raise GoogleCalendarError(
                        f"OAuth credentials file not found: {self.credentials_path}"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, self.scopes
                )
                creds = flow.run_local_server(port=0)
            token_file.write_text(creds.to_json())

        return creds

    def create_event(
        self,
        title: str,
        start: datetime,
        end: datetime | None = None,
        description: str = "",
        timezone: str = "America/New_York",
    ) -> dict:
        """Create a calendar event. If end is None, defaults to start + 1 hour."""
        if end is None:
            end = start + timedelta(hours=1)
        body = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start.isoformat(), "timeZone": timezone},
            "end": {"dateTime": end.isoformat(), "timeZone": timezone},
        }
        try:
            event = (
                self.service.events()
                .insert(calendarId=self.calendar_id, body=body)
                .execute()
            )
            return {
                "event_id": event["id"],
                "html_link": event.get("htmlLink"),
                "title": event.get("summary"),
            }
        except HttpError as e:
            raise GoogleCalendarError(f"create_event failed: {e}") from e

    def update_event(
        self,
        event_id: str,
        title: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        description: str | None = None,
        timezone: str = "America/New_York",
    ) -> dict:
        """Patch fields on an existing event. Only non-None args are updated."""
        patch: dict[str, Any] = {}
        if title is not None:
            patch["summary"] = title
        if description is not None:
            patch["description"] = description
        if start is not None:
            patch["start"] = {"dateTime": start.isoformat(), "timeZone": timezone}
        if end is not None:
            patch["end"] = {"dateTime": end.isoformat(), "timeZone": timezone}

        if not patch:
            return {"event_id": event_id, "updated": False, "reason": "no fields"}

        try:
            event = (
                self.service.events()
                .patch(calendarId=self.calendar_id, eventId=event_id, body=patch)
                .execute()
            )
            return {
                "event_id": event["id"],
                "updated": True,
                "updated_fields": list(patch.keys()),
            }
        except HttpError as e:
            raise GoogleCalendarError(f"update_event failed: {e}") from e

    def find_event(
        self,
        query: str,
        time_min: datetime | None = None,
        time_max: datetime | None = None,
    ) -> list[dict]:
        """Search events by text query within an optional time window."""
        params: dict[str, Any] = {
            "calendarId": self.calendar_id,
            "q": query,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if time_min is not None:
            params["timeMin"] = time_min.isoformat() + "Z"
        if time_max is not None:
            params["timeMax"] = time_max.isoformat() + "Z"
        try:
            resp = self.service.events().list(**params).execute()
            items = resp.get("items", [])
            return [
                {
                    "event_id": e["id"],
                    "title": e.get("summary", ""),
                    "start": e.get("start", {}).get("dateTime")
                    or e.get("start", {}).get("date"),
                    "description": e.get("description", ""),
                    "html_link": e.get("htmlLink"),
                }
                for e in items
            ]
        except HttpError as e:
            raise GoogleCalendarError(f"find_event failed: {e}") from e

    def list_upcoming(self, days_ahead: int = 90) -> list[dict]:
        """List events within the next N days (useful for sync comparisons)."""
        now = datetime.utcnow()
        return self.find_event(
            query="", time_min=now, time_max=now + timedelta(days=days_ahead)
        )

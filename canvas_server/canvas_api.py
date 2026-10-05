"""Canvas REST API client.

Thin wrapper around the Canvas v1 API. All methods return structured dicts
rather than Pydantic models so the MCP server layer stays in control of
serialization.
"""
from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)


class CanvasAPIError(Exception):
    pass


class CanvasAPI:
    def __init__(self, api_token: str, base_url: str):
        if not api_token:
            raise ValueError("Canvas API token is required")
        if not base_url:
            raise ValueError("Canvas base URL is required")
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {api_token}",
                "Accept": "application/json",
            }
        )

    def _get(self, path: str, params: dict | None = None) -> Any:
        url = f"{self.base_url}/api/v1{path}"
        logger.debug("GET %s params=%s", url, params)
        resp = self.session.get(url, params=params, timeout=30)
        if not resp.ok:
            raise CanvasAPIError(f"{resp.status_code} {resp.reason}: {resp.text[:200]}")
        return resp.json()

    def _get_paginated(self, path: str, params: dict | None = None) -> list[dict]:
        """Follow Canvas Link headers for pagination."""
        results: list[dict] = []
        url: str | None = f"{self.base_url}/api/v1{path}"
        p = dict(params or {})
        p.setdefault("per_page", 100)
        while url:
            resp = self.session.get(url, params=p, timeout=30)
            if not resp.ok:
                raise CanvasAPIError(
                    f"{resp.status_code} {resp.reason}: {resp.text[:200]}"
                )
            results.extend(resp.json())
            url = self._next_link(resp.headers.get("Link", ""))
            p = {}  # params already encoded in next URL
        return results

    @staticmethod
    def _next_link(link_header: str) -> str | None:
        for part in link_header.split(","):
            if 'rel="next"' in part:
                return part.split(";")[0].strip().strip("<>")
        return None

    def get_courses(self) -> list[dict]:
        """Return active courses with id, name, and course_code."""
        raw = self._get_paginated(
            "/courses",
            params={"enrollment_state": "active", "include[]": "term"},
        )
        return [
            {
                "course_id": c["id"],
                "course_name": c.get("name", ""),
                "course_code": c.get("course_code", ""),
            }
            for c in raw
            if c.get("name")
        ]

    def get_assignments(self, course_id: int) -> list[dict]:
        """Return assignments for a course."""
        raw = self._get_paginated(f"/courses/{course_id}/assignments")
        return [
            {
                "assignment_id": a["id"],
                "name": a.get("name", ""),
                "due_at": a.get("due_at"),
                "html_url": a.get("html_url"),
                "description": a.get("description") or "",
            }
            for a in raw
        ]

    def get_syllabus(self, course_id: int) -> dict:
        """Return raw syllabus HTML for a course (may be empty string)."""
        data = self._get(
            f"/courses/{course_id}",
            params={"include[]": "syllabus_body"},
        )
        return {
            "course_id": course_id,
            "course_name": data.get("name", ""),
            "syllabus_html": data.get("syllabus_body") or "",
        }

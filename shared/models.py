from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class EventType(str, Enum):
    ASSIGNMENT = "assignment"
    HOMEWORK = "homework"
    QUIZ = "quiz"
    EXAM = "exam"
    MIDTERM = "midterm"
    FINAL = "final"
    PROJECT = "project"
    PRESENTATION = "presentation"
    PAPER = "paper"
    LAB = "lab"
    OTHER = "other"


class EventSource(str, Enum):
    CANVAS_ASSIGNMENT = "canvas_assignment"
    CANVAS_CALENDAR = "canvas_calendar_event"
    CANVAS_SYLLABUS = "canvas_syllabus"
    CANVAS_ANNOUNCEMENT = "canvas_announcement"


class Course(BaseModel):
    course_id: int
    course_name: str
    course_code: str


class AcademicEvent(BaseModel):
    course: str = Field(..., description="Course code, e.g. 'CS 3200'")
    title: str = Field(..., description="Event title, e.g. 'Homework 4'")
    event_type: EventType
    start_datetime: Optional[datetime] = None
    due_datetime: Optional[datetime] = None
    source: EventSource
    source_id: Optional[str] = None

    def dedup_key(self) -> tuple[str, str, str]:
        """Key for deduplication: course + normalized title + date (day-level)."""
        date = self.due_datetime or self.start_datetime
        date_str = date.date().isoformat() if date else ""
        return (
            self.course.lower().strip(),
            self._normalize_title(self.title),
            date_str,
        )

    @staticmethod
    def _normalize_title(title: str) -> str:
        """Lowercase, strip punctuation, normalize HW -> Homework."""
        import re

        t = title.lower().strip()
        t = re.sub(r"\bhw\b", "homework", t)
        t = re.sub(r"[^\w\s]", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        return t

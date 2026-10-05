"""Rule-based syllabus parser.

Extracts academic events (exams, projects, deadlines) from syllabus HTML or
plain text. No LLM — pure regex + dateutil. The strategy:

1. Strip HTML (tables become line-separated text).
2. Split into candidate lines.
3. For each line that mentions an event keyword, try to extract a date.
4. Emit an AcademicEvent only if a real date was found. Never invent one.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Iterable

from bs4 import BeautifulSoup
from dateutil import parser as dateparser

from shared.models import AcademicEvent, EventSource, EventType

logger = logging.getLogger(__name__)


# Order matters: more specific terms first so "Final Exam" beats "Final".
EVENT_KEYWORDS: list[tuple[str, EventType]] = [
    ("final exam", EventType.FINAL),
    ("midterm exam", EventType.MIDTERM),
    ("midterm", EventType.MIDTERM),
    ("final project", EventType.PROJECT),
    ("final", EventType.FINAL),
    ("exam", EventType.EXAM),
    ("quiz", EventType.QUIZ),
    ("homework", EventType.HOMEWORK),
    ("project", EventType.PROJECT),
    ("presentation", EventType.PRESENTATION),
    ("paper", EventType.PAPER),
    ("essay", EventType.PAPER),
    ("lab", EventType.LAB),
    ("assignment", EventType.ASSIGNMENT),
    (r"\bhw\b", EventType.HOMEWORK),  # standalone HW only
]

# Phrases that mean "we don't actually know the date yet".
VAGUE_PHRASES = [
    "see university",
    "see schedule",
    "tbd",
    "tba",
    "to be determined",
    "to be announced",
]

MONTH_RE = (
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)"
)

DATE_PATTERNS = [
    # "October 22", "Oct. 22, 2026", "Oct 22 at 3 PM"
    rf"{MONTH_RE}\.?\s+\d{{1,2}}(?:,?\s*\d{{4}})?(?:\s+at\s+\d{{1,2}}(?::\d{{2}})?\s*(?:AM|PM|am|pm))?",
    # "Thursday, October 22"
    rf"(?:Mon|Tues?|Wed(?:nes)?|Thurs?|Fri|Sat|Sun)[a-z]*,?\s+{MONTH_RE}\.?\s+\d{{1,2}}(?:,?\s*\d{{4}})?",
    # "10/22", "10/22/2026", "10-22-2026"
    r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b",
]
DATE_RE = re.compile("|".join(DATE_PATTERNS), re.IGNORECASE)


def html_to_text(html: str) -> str:
    """Convert syllabus HTML to plain text, preserving row-level structure.

    Each table row, list item, paragraph, or <br> break becomes one line.
    Cells within a row stay joined with a separator so an event like
    "Midterm Exam | October 22" stays matchable on a single line.
    """
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    # Keep cells on the same row joined by a visible separator.
    for cell in soup.find_all(["td", "th"]):
        cell.insert_before(" | ")
    # Rows and other block-level markers become hard line breaks.
    for block in soup.find_all(["tr", "li", "p", "br", "div"]):
        block.append("\n")
    text = soup.get_text(separator=" ")
    lines = [re.sub(r"\s+", " ", line).strip(" |").strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _classify(line: str) -> EventType | None:
    """Return the first matching event type for a line, or None."""
    low = line.lower()
    for keyword, event_type in EVENT_KEYWORDS:
        if keyword.startswith(r"\b"):
            if re.search(keyword, low):
                return event_type
        elif keyword in low:
            return event_type
    return None


def _extract_date(line: str, default_year: int) -> datetime | None:
    """Pull the first parseable date from a line, or None."""
    match = DATE_RE.search(line)
    if not match:
        return None
    candidate = match.group(0)
    try:
        default = datetime(default_year, 1, 1)
        parsed = dateparser.parse(candidate, default=default, fuzzy=True)
        return parsed
    except (ValueError, OverflowError) as e:
        logger.debug("Failed to parse date %r: %s", candidate, e)
        return None


def _derive_title(line: str, event_type: EventType) -> str:
    """Pick a human-readable title from the line.

    Prefer text before a colon or dash, falling back to the event type.
    """
    for sep in [":", " - ", " — ", " – "]:
        if sep in line:
            left = line.split(sep, 1)[0].strip()
            if left and len(left) < 80:
                return left
    # Fall back to the event type titleized.
    return event_type.value.title()


def parse_syllabus(
    html_or_text: str,
    course_code: str,
    default_year: int | None = None,
) -> list[AcademicEvent]:
    """Extract academic events from a syllabus.

    Args:
        html_or_text: raw syllabus content (HTML or plain text).
        course_code: course code to attach to events (e.g. "CS 3200").
        default_year: year to assume for dates missing a year.
            Defaults to the current year.
    """
    if default_year is None:
        default_year = datetime.now().year

    text = html_to_text(html_or_text) if "<" in html_or_text else html_or_text
    if not text:
        return []

    events: list[AcademicEvent] = []
    seen_keys: set = set()

    for raw_line in _iter_lines(text):
        line = raw_line.strip()
        if not line or len(line) > 500:
            continue
        if any(phrase in line.lower() for phrase in VAGUE_PHRASES):
            continue

        event_type = _classify(line)
        if event_type is None:
            continue

        date = _extract_date(line, default_year)
        if date is None:
            continue

        title = _derive_title(line, event_type)
        event = AcademicEvent(
            course=course_code,
            title=title,
            event_type=event_type,
            due_datetime=date,
            source=EventSource.CANVAS_SYLLABUS,
        )
        key = event.dedup_key()
        if key in seen_keys:
            continue
        seen_keys.add(key)
        events.append(event)

    return events


def _iter_lines(text: str) -> Iterable[str]:
    """Yield lines from text, splitting on semicolons which separate sub-clauses."""
    for line in text.splitlines():
        for part in line.split(";"):
            yield part

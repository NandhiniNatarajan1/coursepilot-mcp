import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).parent

CANVAS_API_TOKEN = os.getenv("CANVAS_API_TOKEN", "")
CANVAS_BASE_URL = os.getenv("CANVAS_BASE_URL", "").rstrip("/")

GOOGLE_CREDENTIALS_JSON = os.getenv(
    "GOOGLE_CREDENTIALS_JSON", str(PROJECT_ROOT / "credentials.json")
)
GOOGLE_TOKEN_JSON = str(PROJECT_ROOT / "token.json")
GOOGLE_CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar"]

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Comma-separated substrings. If set, only courses whose course_code contains
# one of these substrings are synced. Example: "202710" for Fall 2026 at
# Northeastern. Leave empty to sync every active course Canvas returns.
TERM_FILTER = [s.strip() for s in os.getenv("TERM_FILTER", "").split(",") if s.strip()]


def validate() -> list[str]:
    """Return a list of missing config values. Empty list = all good."""
    missing = []
    if not CANVAS_API_TOKEN:
        missing.append("CANVAS_API_TOKEN")
    if not CANVAS_BASE_URL:
        missing.append("CANVAS_BASE_URL")
    if not Path(GOOGLE_CREDENTIALS_JSON).exists():
        missing.append(f"GOOGLE_CREDENTIALS_JSON (file not found: {GOOGLE_CREDENTIALS_JSON})")
    return missing

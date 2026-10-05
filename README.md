# CoursePilot MCP

A full-stack learning project that connects Canvas LMS to Google Calendar using the Model Context Protocol (MCP).

## Project Goal

Understand MCP servers by building a real-world application that:
1. Retrieves courses and assignments from Canvas
2. Extracts academic dates from course syllabi
3. Syncs all events to Google Calendar

## Architecture

```
Canvas LMS
   |
   v
Canvas MCP Server (tools: get_courses, get_assignments, get_syllabus)
   |
   v
Sync Orchestrator (MCP Client)
   |
   v
Google Calendar MCP Server (tools: create_event, update_event, find_event)
   |
   v
Google Calendar
```

## MCP Learning Path

- **Phase 1**: Data models (no MCP)
- **Phase 2**: Canvas MCP server (first server, tool definitions)
- **Phase 3**: Google Calendar MCP server (second server, patterns)
- **Phase 4**: Orchestration script (MCP client, composition) ← "aha" moment
- **Phase 5**: Tests & documentation

## Setup

### Prerequisites
- Python 3.12+
- A Canvas account with API token access
- A Google account with Calendar access

### Installation

1. Clone the repo:
   ```bash
   git clone https://github.com/NandhiniNatarajan1/coursepilot-mcp.git
   cd coursepilot-mcp
   ```

2. Create virtual environment:
   ```bash
   python -m venv venv
   # Windows PowerShell:
   .\venv\Scripts\Activate.ps1
   # macOS/Linux:
   source venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### Credentials

**Canvas:**
1. Log into Canvas → Account → Settings → New Access Token.
2. Copy the token.

**Google Calendar (one-time OAuth setup):**
1. Go to [Google Cloud Console](https://console.cloud.google.com/) and create a project.
2. Enable the **Google Calendar API** for that project.
3. Create OAuth 2.0 credentials of type **Desktop app**.
4. Download the `credentials.json` and place it in the project root.
5. First run of the sync will open a browser for consent and write `token.json` next to it.

**Env file:**
```bash
cp .env.example .env
# Edit .env:
#   CANVAS_API_TOKEN=...
#   CANVAS_BASE_URL=https://<your-school>.instructure.com
```

## Running the Project

### Full sync (production use)
```bash
python sync_orchestrator.py
```
This spawns both MCP servers as subprocesses, collects events, dedupes, and syncs to Google Calendar.

### Running a server manually (for MCP inspection)
```bash
# Canvas server:
python -m canvas_server.server

# Calendar server:
python -m google_calendar_server.server
```
Both speak the MCP protocol over stdio and are usable from any MCP client (including Claude Desktop with the appropriate config).

## Testing

```bash
pytest tests/
```

## Project Structure

```
coursepilot-mcp/
├── shared/              # Shared data models
│   └── models.py
├── canvas_server/       # Canvas MCP server
│   ├── server.py
│   ├── canvas_api.py
│   └── syllabus_parser.py
├── google_calendar_server/  # Google Calendar MCP server
│   ├── server.py
│   └── google_api.py
├── tests/              # Unit & integration tests
├── sync_orchestrator.py # Main sync script (MCP client)
├── config.py           # Configuration management
├── .env.example        # Environment variables template
├── requirements.txt    # Python dependencies
└── README.md
```

## MCP Concepts Learned

- Tool schema definition and JSON validation
- Async tool handlers and server lifecycle
- Running MCP servers as subprocesses
- MCP client patterns and tool composition
- Error handling across multiple servers
- Stateful vs. stateless tool operations

## Notes

This is a learning project designed to understand MCP. It prioritizes clarity and modularity over production features.

For detailed implementation notes, see the comments in each module.

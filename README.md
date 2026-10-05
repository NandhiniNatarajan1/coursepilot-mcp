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

## MCP Learning Notes

The whole point of this project is to understand MCP. Here are the concrete ideas each phase teaches, with pointers to where in the code to look.

### 1. A tool is just a decorated function

In both servers, a tool is a Python function that returns JSON-serializable data:

```python
@mcp.tool()
def canvas_get_courses() -> list[dict]:
    """List the student's active Canvas courses."""
    return _api().get_courses()
```

The docstring becomes the tool's description for the LLM. The type hints become the input/output schema. See [`canvas_server/server.py`](canvas_server/server.py).

### 2. A server is a long-running process that speaks over stdio

Each server's `__main__` just calls `mcp.run()`. That blocks and listens for JSON-RPC messages on stdin/stdout. You never implement the protocol yourself.

### 3. Two servers do not share memory

Even though they run on the same machine, they're independent OS processes. The Google Calendar server has no idea what Canvas is. This is a feature, not a bug — it keeps responsibilities clean.

### 4. The client composes servers

[`sync_orchestrator.py`](sync_orchestrator.py) is the "aha" moment. It:

1. Spawns both servers as subprocesses (`stdio_client` + `StdioServerParameters`).
2. Opens a `ClientSession` against each.
3. Calls tools via `session.call_tool(name, arguments)`.

Note what it does NOT do: `import canvas_api`, `from google_api import ...`, etc. The orchestrator never touches the server internals. If you swap `canvas_server` for a different implementation that honors the same tool contract, the orchestrator keeps working.

### 5. Tool results are structured content, not raw returns

MCP wraps tool returns in a `content` list of items. For JSON data our tools return, we unwrap it in `_call`:

```python
for item in result.content:
    return json.loads(item.text)
```

See [`sync_orchestrator.py:49`](sync_orchestrator.py#L49).

### 6. Dedup belongs in the client, not the servers

Each server is stateless and single-purpose. Dedup logic (source priority, title normalization) lives in the orchestrator because it depends on business rules that cross both domains. See `deduplicate()` in the orchestrator and `AcademicEvent.dedup_key()` in [`shared/models.py`](shared/models.py).

## Testing

```bash
pytest tests/
```

25 tests cover syllabus parsing, deduplication, and the sync pipeline (with mocked MCP sessions — no real API calls needed).

## Notes

This is a learning project. It prioritizes clarity and modularity over production features — no database, no retry logic, no LLM. Those can be added later without changing the server contracts.

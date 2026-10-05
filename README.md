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
- Canvas API token
- Google OAuth credentials

### Installation

1. Clone the repo:
   ```bash
   git clone https://github.com/yourusername/coursepilot-mcp.git
   cd coursepilot-mcp
   ```

2. Create virtual environment:
   ```bash
   python -m venv venv
   source venv/Scripts/activate  # Windows
   # source venv/bin/activate    # macOS/Linux
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Configure credentials:
   ```bash
   cp .env.example .env
   # Edit .env with your Canvas API token and Google credentials path
   ```

## Running the Project

### Canvas Server
```bash
python canvas_server/server.py
```

### Google Calendar Server
```bash
python google_calendar_server/server.py
```

### Full Sync
```bash
python sync_orchestrator.py
```

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

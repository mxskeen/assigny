# Assigny Backend (FastAPI + MCP)

backend for doctor appointment assistant with MCP tools.

## Setup

1. Create virtualenv and install deps:
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
```

2. Configure env:
- Copy `backend/env.example` to `backend/.env` and fill values
- LLM: set `GEMINI_API_KEY` (default `gemini-2.5-flash`).

3. Initialize DB tables and seed demo data:
```bash
python -m app.startup
python -m app.seed
```

4. Run API:
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health check: `GET /health`

## Agent Endpoint
- `POST /agent/chat` body `{ "message": string, "session_id": string }`
- launches MCP server `app.mcp_server` over stdio.
- Uses Gemini 2.5 Flash via `google-generativeai` to decide tool usage.

## MCP Tools
- `check_doctor_availability`
- `book_appointment_tool`
- `appointment_stats_tool`

## Integrations
- Google Calendar (OAuth refresh)
- SMTP email
- Slack messaging

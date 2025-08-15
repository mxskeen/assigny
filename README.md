# Assigny

Smart AI-assisted doctor appointment booking & practice analytics.

## Stack
- Backend: FastAPI + MCP tools
- Frontend: React + TypeScript
- DB: SQLite (dev) / PostgreSQL (prod)
- LLM: OpenAI GPT‑4.1
- Integrations: Google Calendar, SMTP Email, Slack

## Core Features
Patients:
- Natural language booking & availability
- Multi‑turn chat
- Email confirmations

Doctors:
- Stats & summaries
- Condition-based patient queries
- Schedule views
- Slack daily summaries

System:
- MCP tool discovery & forced (anti‑hallucination)
- Role-based access (patient / doctor)
- Session context memory

## Environment (.env)
```
OPENAI_API_KEY=
GOOGLE_CALENDAR_ID=
EMAIL_USER=
EMAIL_PASSWORD=
SLACK_BOT_TOKEN=
SLACK_CHANNEL_ID=
```

## Quick Start
Backend:
```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp env.example .env  # fill values
uvicorn app.main:app --reload --port 8000
```
or for backend:
```
cd /home/user/assigny/backend && source /home/user/assigny/.venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Frontend:
```bash
cd frontend
npm install
npm run dev
```

URLs:
- App: http://localhost:5173
- API: http://localhost:8000
- Docs: http://localhost:8000/docs

## Chat API
```
POST /agent/chat
{ "message": "...", "session_id": "abc", "user_type": "patient|doctor" }
```

Health:
```
GET /health
```

## MCP Tools (auto)
- appointment_stats_tool
- list_appointments_tool
- patients_by_reason_tool
- check_doctor_availability
- book_appointment_tool
- register_patient_tool

## Example
```bash
curl -X POST http://localhost:8000/agent/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"How many appointments today?","session_id":"test","user_type":"doctor"}'
```

## Add a Tool
1. Define + decorate in `mcp_server.py`
2. Update arg handling / formatting in `agent.py`

## Schema (tables)
doctors | patients | appointments | doctor_availability



## Troubleshooting
No appointments :- seed DB.
Hallucination :- check logs (forced tool calls) + API key.
Tool errors :- MCP server running & arg formats.


from __future__ import annotations

from datetime import datetime, date, timedelta
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text as sql_text

from .config import get_settings
from .db import SessionLocal
from .repositories import book_appointment, daily_stats, find_availability_slots, get_doctor_by_name, get_patient_by_email, cancel_appointment, list_appointments, cancel_appointments_by_date, patients_by_reason, list_doctors
from .schemas import BookAppointmentInput, DoctorAvailabilityQuery, DoctorAvailabilityResult, StatsQuery, PatientCreate, CancelAppointmentInput, ListAppointmentsQuery, CancelByDateInput, PatientsByReasonQuery
from .models import Patient, Appointment, Doctor, DoctorAvailability

mcp = FastMCP("assigny")


async def _get_session() -> AsyncSession:
	return SessionLocal()


async def _send_email(to_email: str, subject: str, body: str) -> None:
	settings = get_settings()
	host = settings.SMTP_HOST
	user = settings.SMTP_USER
	password = settings.SMTP_PASSWORD
	port = settings.SMTP_PORT
	from_email = settings.FROM_EMAIL or user
	if not (host and user and password and from_email):
		return
	import smtplib
	from email.mime.text import MIMEText
	msg = MIMEText(body)
	msg["Subject"] = subject
	msg["From"] = from_email
	msg["To"] = to_email
	with smtplib.SMTP(host, port) as server:
		server.starttls()
		server.login(user, password)
		server.send_message(msg)


async def _create_calendar_event(start_at: datetime, end_at: datetime, summary: str, description: str | None = None) -> str:
	settings = get_settings()
	from google.oauth2.credentials import Credentials
	from googleapiclient.discovery import build
	if not (settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET and settings.GOOGLE_REFRESH_TOKEN and settings.GOOGLE_CALENDAR_ID):
		return ""
	creds = Credentials(
		token=None,
		refresh_token=settings.GOOGLE_REFRESH_TOKEN,
		token_uri="https://oauth2.googleapis.com/token",
		client_id=settings.GOOGLE_CLIENT_ID,
		client_secret=settings.GOOGLE_CLIENT_SECRET,
		scopes=["https://www.googleapis.com/auth/calendar"],
	)
	service = build("calendar", "v3", credentials=creds, cache_discovery=False)
	body = {
		"summary": summary,
		"description": description or "",
		"start": {"dateTime": start_at.isoformat(), "timeZone": "UTC"},
		"end": {"dateTime": end_at.isoformat(), "timeZone": "UTC"},
	}
	event = service.events().insert(calendarId=settings.GOOGLE_CALENDAR_ID, body=body).execute()
	return event.get("id", "")


async def _send_slack_message(channel_id: str, text: str) -> None:
	settings = get_settings()
	token = settings.SLACK_BOT_TOKEN
	if not (token and channel_id):
		return
	from slack_sdk import WebClient
	client = WebClient(token=token)
	client.chat_postMessage(channel=channel_id, text=text)


@mcp.tool()
async def http_get(url: str, timeout_seconds: int = 10) -> str:
	"""Fetch the content of a public URL as text. Returns up to 20k chars.

	Args:
		url: Fully-qualified http(s) URL to fetch
		timeout_seconds: Request timeout
	"""
	try:
		async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
			resp = await client.get(url)
			resp.raise_for_status()
			text = resp.text
			return text[:20000]
	except Exception as e:
		return f"error: {e}"


@mcp.tool()
async def list_doctors_tool() -> dict[str, Any]:
	"""Return all doctors (id, name, email, specialty)."""
	session = await _get_session()
	async with session as db:
		docs = await list_doctors(db)
		return {"doctors": [{"id": d.id, "name": d.name, "email": d.email, "specialty": d.specialty} for d in docs]}


@mcp.tool()
async def db_schema_tool() -> dict[str, Any]:
	"""Return a compact JSON description of the database schema for NL2SQL. Read-only use recommended."""
	def model_schema(model) -> dict[str, Any]:
		cols = []
		for c in model.__table__.columns:  # type: ignore[attr-defined]
			cols.append({"name": c.name, "type": str(c.type), "nullable": c.nullable})
		return {"table": model.__tablename__, "columns": cols}  # type: ignore[attr-defined]
	return {
		"tables": [
			model_schema(Doctor),
			model_schema(Patient),
			model_schema(Appointment),
			model_schema(DoctorAvailability),
		]
	}


@mcp.tool()
async def sql_read_tool(sql: str, params: dict[str, Any] | None = None, row_limit: int = 200) -> dict[str, Any]:
	"""Execute a safe, read-only SQL SELECT and return rows as JSON.
	Constraints: statement must start with SELECT and must not contain modifying keywords.
	Args: sql (use named parameters like :for_date), params optional dict, row_limit caps returned rows.
	"""
	s = (sql or "").strip()
	if not s.lower().startswith("select"):
		return {"error": "Only SELECT queries are allowed"}
	banned = [";", " insert ", " update ", " delete ", " drop ", " alter ", " create ", " truncate ", " merge ", " grant ", " revoke ", " vacuum ", " attach ", " pragma "]
	low = f" {s.lower()} "
	if any(b in low for b in banned):
		return {"error": "Unsafe or forbidden SQL detected"}
	try:
		session = await _get_session()
		async with session as db:
			res = await db.execute(sql_text(s), params or {})
			rows = [dict(r) for r in res.mappings().fetchmany(row_limit)]
			return {"rows": rows, "row_count": len(rows)}
	except Exception as e:
		return {"error": str(e)}


@mcp.tool()
async def resolve_date_tool(text: str, reference_yyyy_mm_dd: str | None = None) -> dict[str, Any]:
	"""Resolve a natural phrase like 'today', 'tomorrow', or 'next Monday' to YYYY-MM-DD.
	Args: text, reference_yyyy_mm_dd optional (defaults to today's UTC date)
	Returns: {"date": "YYYY-MM-DD"}
	"""
	ref = date.fromisoformat(reference_yyyy_mm_dd) if reference_yyyy_mm_dd else datetime.utcnow().date()
	s = (text or "").strip().lower()
	if not s:
		return {"error": "empty text"}
	# Simple phrases
	if "tomorrow" in s:
		return {"date": (ref + timedelta(days=1)).isoformat()}
	if "today" in s:
		return {"date": ref.isoformat()}
	if "yesterday" in s:
		return {"date": (ref - timedelta(days=1)).isoformat()}
	# Weekdays
	week = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
	for idx, name in enumerate(week):
		if f"next {name}" in s:
			current = ref.weekday()
			delta = (idx - current + 7) % 7
			if delta == 0:
				delta = 7
			return {"date": (ref + timedelta(days=delta)).isoformat()}
		if name in s:
			current = ref.weekday()
			delta = (idx - current + 7) % 7
			if delta == 0:
				delta = 7
			return {"date": (ref + timedelta(days=delta)).isoformat()}
	# Fallback: return ref (caller can override)
	return {"date": ref.isoformat()}


@mcp.tool()
async def check_doctor_availability(query: dict[str, Any]) -> dict[str, Any]:
	"""
	Check a doctor's availability for a given date and optional part of day.
	Args:
		query: {"doctor_name": str, "date": "YYYY-MM-DD", "part_of_day": str | None}
	Returns:
		{"doctor_id": int, "doctor_name": str, "available_slots": ["2025-08-14T09:00-09:30", ...]}
	If no slots are found on the requested date, searches forward up to 21 days and returns the
	first day's slots, if any.
	"""
	try:
		payload = DoctorAvailabilityQuery(**query)
	except ValidationError as e:
		return {"error": str(e)}

	session = await _get_session()
	async with session as db:
		doctor = await get_doctor_by_name(db, payload.doctor_name)
		if not doctor:
			return {"error": "Doctor not found"}
		# Try requested date
		slots = await find_availability_slots(db, doctor.id, payload.date, payload.part_of_day)
		# Fallback: search next 21 days if empty
		search_date = payload.date
		if not slots:
			for _ in range(21):
				search_date = search_date + timedelta(days=1)
				slots = await find_availability_slots(db, doctor.id, search_date, payload.part_of_day)
				if slots:
					break
		formatted = [f"{s.isoformat()}-{e.isoformat()}" for s, e in slots]
		return DoctorAvailabilityResult(doctor_id=doctor.id, doctor_name=doctor.name, available_slots=formatted).model_dump()


@mcp.tool()
async def register_patient_tool(data: dict[str, Any]) -> dict[str, Any]:
	"""Register a new patient in the system.
	
	Args:
		data: Patient information dict with name/first_name/last_name, email, and optional primary_condition
	"""
	# Accept common synonyms
	if "patient_email" in data and "email" not in data:
		data = {**data, "email": data.get("patient_email")}
	
	try:
		payload = PatientCreate(**data)
	except ValidationError as e:
		return {"error": str(e)}
	
	async with SessionLocal() as db:
		try:
			# Handle name variations
			if payload.first_name or payload.last_name:
				full_name = f"{payload.first_name or ''} {payload.last_name or ''}".strip()
			else:
				full_name = payload.name or ""
			
			if not full_name:
				return {"error": "Patient name is required"}
			
			email = str(payload.email)
			if not email:
				return {"error": "Patient email is required"}
			
			# Check if patient already exists
			existing = await get_patient_by_email(db, email)
			if existing:
				return {"error": f"Patient with email {email} already exists"}
			
			# Create new patient
			patient = Patient(
				name=full_name,
				email=email,
				primary_condition=payload.primary_condition
			)
			db.add(patient)
			await db.commit()
			await db.refresh(patient)
			
			# Send Slack notification for new patient registration
			settings = get_settings()
			if settings.SLACK_BOT_TOKEN and settings.SLACK_CHANNEL_ID:
				slack_text = (
					f"🆕 **New Patient Registered!**\n\n"
					f"👤 **Name:** {full_name}\n"
					f"📧 **Email:** {email}\n"
					f"🏥 **Primary Condition:** {payload.primary_condition or 'Not specified'}\n"
					f"📅 **Registered:** {datetime.now().strftime('%B %d, %Y at %I:%M %p')}"
				)
				await _send_slack_message(settings.SLACK_CHANNEL_ID, slack_text)
			
			return {"message": f"Patient {full_name} registered successfully", "patient_id": patient.id}
		except Exception as e:
			await db.rollback()
			return {"error": f"Registration failed: {str(e)}"}


@mcp.tool()
async def book_appointment_tool(data: dict[str, Any]) -> dict[str, Any]:
	"""
	Book an appointment if the slot is free, add to calendar, and send confirmation email.
	Args:
		{"doctor_name": str, "patient_email": str, "start_at": iso, "end_at": iso, "description": str | None}
	Returns:
		{"appointment_id": int, "calendar_event_id": str, "message": str}
	"""
	try:
		payload = BookAppointmentInput(**data)
	except ValidationError as e:
		return {"error": str(e)}

	session = await _get_session()
	async with session as db:
		doctor = await get_doctor_by_name(db, payload.doctor_name)
		if not doctor:
			return {"error": "Doctor not found"}
		patient = await get_patient_by_email(db, payload.patient_email)
		if not patient:
			return {"error": "Patient not found"}

		try:
			appt = await book_appointment(db, doctor, patient, payload.start_at, payload.end_at, payload.description)
		except Exception as e:
			return {"error": str(e)}

		event_id = await _create_calendar_event(payload.start_at, payload.end_at, f"Appointment: {doctor.name}", payload.description)
		await _send_email(
			to_email=patient.email,
			subject=f"Appointment confirmed with {doctor.name}",
			body=f"Your appointment is scheduled from {payload.start_at} to {payload.end_at}. Reason: {payload.description or 'N/A'}.",
		)
		# Notify doctor as well
		await _send_email(
			to_email=doctor.email,
			subject=f"New appointment booked (#{appt.id})",
			body=f"Patient: {patient.name} ({patient.email})\nWhen: {payload.start_at} to {payload.end_at}\nReason: {payload.description or 'N/A'}",
		)
		
		# Send Slack notification for new appointment booking
		settings = get_settings()
		if settings.SLACK_BOT_TOKEN and settings.SLACK_CHANNEL_ID:
			start_time = payload.start_at.strftime('%B %d, %Y at %I:%M %p')
			end_time = payload.end_at.strftime('%I:%M %p')
			slack_text = (
				f"📅 **New Appointment Booked!**\n\n"
				f"👨‍⚕️ **Doctor:** {doctor.name}\n"
				f"👤 **Patient:** {patient.name} ({patient.email})\n"
				f"🕐 **Time:** {start_time} - {end_time}\n"
				f"🏥 **Reason:** {payload.description or 'Not specified'}\n"
				f"🆔 **Appointment ID:** #{appt.id}"
			)
			await _send_slack_message(settings.SLACK_CHANNEL_ID, slack_text)
		
		return {"appointment_id": appt.id, "calendar_event_id": event_id, "message": f"Booked appointment #{appt.id} with {doctor.name} for {patient.name}."}


@mcp.tool()
async def cancel_appointment_tool(data: dict[str, Any]) -> dict[str, Any]:
	"""Cancel an appointment and notify the patient by email.
	Args: {"appointment_id": int, "reason": str | None}
	Returns: {"appointment_id": int, "status": "canceled", "message": str}
	"""
	try:
		payload = CancelAppointmentInput(**data)
	except ValidationError as e:
		return {"error": str(e)}

	session = await _get_session()
	async with session as db:
		appt = await cancel_appointment(db, payload.appointment_id)
		patient = appt.patient
		doctor = appt.doctor
		await _send_email(
			to_email=patient.email,
			subject=f"Appointment canceled with {doctor.name}",
			body=f"Your appointment on {appt.start_at} has been canceled. Reason: {payload.reason or 'not specified'}.",
		)
		return {"appointment_id": appt.id, "status": appt.status, "message": f"Appointment #{appt.id} canceled."}


@mcp.tool()
async def cancel_appointments_by_date_tool(data: dict[str, Any]) -> dict[str, Any]:
	"""Cancel all appointments for a specific date, optionally for a doctor. Notifies each patient by email.
	Args: {"for_date": "YYYY-MM-DD", "doctor_name": str | None, "reason": str | None}
	Returns: {"canceled": int}
	"""
	try:
		payload = CancelByDateInput(**data)
	except ValidationError as e:
		return {"error": str(e)}

	session = await _get_session()
	async with session as db:
		doctor_id = None
		doctor_name = None
		if payload.doctor_name:
			doctor = await get_doctor_by_name(db, payload.doctor_name)
			if not doctor:
				return {"error": "Doctor not found"}
			doctor_id = doctor.id
			doctor_name = doctor.name
		apps = await cancel_appointments_by_date(db, payload.for_date, doctor_id)
		for appt in apps:
			patient = appt.patient
			doc = appt.doctor
			await _send_email(
				to_email=patient.email,
				subject=f"Appointment canceled with {doc.name}",
				body=f"Your appointment on {appt.start_at} has been canceled. Reason: {payload.reason or 'not specified'}.",
			)
		return {"canceled": len(apps), "doctor": doctor_name, "for_date": str(payload.for_date)}


@mcp.tool()
async def list_appointments_tool(query: dict[str, Any]) -> dict[str, Any]:
	"""List appointments for a date, optionally filter by doctor, patient, and time.
	Args: {"for_date": "YYYY-MM-DD", "doctor_name": str | None, "patient_email": str | None, "at_time": "HH:MM" | None}
	Returns: {"appointments": [ ... ]}
	"""
	try:
		payload = ListAppointmentsQuery(**query)
	except ValidationError as e:
		return {"error": str(e)}

	session = await _get_session()
	async with session as db:
		doctor_id = None
		if payload.doctor_name:
			doctor = await get_doctor_by_name(db, payload.doctor_name)
			if not doctor:
				return {"error": "Doctor not found"}
			doctor_id = doctor.id
		apps = await list_appointments(db, payload.for_date, doctor_id, str(payload.patient_email) if payload.patient_email else None, payload.at_time)
		return {"appointments": apps}


@mcp.tool()
async def patients_by_reason_tool(query: dict[str, Any]) -> dict[str, Any]:
	"""Return patients whose appointment reason matches a phrase on a date, optionally scoped to a doctor.
	Args: {"for_date": "YYYY-MM-DD", "reason_like": str, "doctor_name": str | None}
	Returns: {"patients": [{name,email,appointment_id,start_at,end_at}]}
	"""
	try:
		payload = PatientsByReasonQuery(**query)
	except ValidationError as e:
		return {"error": str(e)}

	session = await _get_session()
	async with session as db:
		doctor_id = None
		if payload.doctor_name:
			doctor = await get_doctor_by_name(db, payload.doctor_name)
			if not doctor:
				return {"error": "Doctor not found"}
			doctor_id = doctor.id
		rows = await patients_by_reason(db, payload.for_date, payload.reason_like, doctor_id)
		return {"patients": rows}


@mcp.tool()
async def appointment_stats_tool(query: dict[str, Any]) -> dict[str, Any]:
	"""
	Return appointment statistics for a given date, optionally filtered by doctor and patient condition.
	Args: {"for_date": "YYYY-MM-DD", "doctor_name": str | None, "condition_like": str | None, "notify": bool | None, "notify_channel": str | None}
	Returns: {"total_appointments": int, "completed": int, "canceled": int, "by_condition": {str: int} | None}
	"""
	try:
		payload = StatsQuery(**query)
	except ValidationError as e:
		return {"error": str(e)}

	session = await _get_session()
	async with session as db:
		doctor_id = None
		if payload.doctor_name:
			doctor = await get_doctor_by_name(db, payload.doctor_name)
			if not doctor:
				return {"error": "Doctor not found"}
			doctor_id = doctor.id
		stats = await daily_stats(db, payload.for_date or datetime.now().date(), doctor_id, payload.condition_like)
		# Optional Slack notify
		if payload.notify:
			channel = payload.notify_channel or get_settings().SLACK_CHANNEL_ID or ""
			if channel:
				# Get detailed appointment information for Slack
				query_date = payload.for_date or datetime.now().date()
				detailed_appointments = await list_appointments(db, query_date, doctor_id)
				
				# Format detailed summary with correct date
				date_str = query_date.strftime("%B %d, %Y")
				text = f"📅 **Appointment Summary for {date_str}**\n\n"
				text += f"📊 **Overview:** {stats['total_appointments']} total | {stats['completed']} completed | {stats['canceled']} canceled\n\n"
				
				if detailed_appointments:
					text += "👥 **Detailed Appointments:**\n"
					for apt in detailed_appointments:
						# Handle timezone-aware datetime parsing
						start_dt_str = apt["start_at"]
						end_dt_str = apt["end_at"]
						
						# Remove timezone info if present for simpler parsing
						if start_dt_str.endswith('Z'):
							start_dt_str = start_dt_str[:-1]
						if end_dt_str.endswith('Z'):
							end_dt_str = end_dt_str[:-1]
						
						start_dt = datetime.fromisoformat(start_dt_str)
						end_dt = datetime.fromisoformat(end_dt_str)
						start_time = start_dt.strftime("%I:%M %p")
						end_time = end_dt.strftime("%I:%M %p")
						status_emoji = "✅" if apt["status"] == "completed" else "❌" if apt["status"] == "canceled" else "⏰"
						reason = f" - {apt['description']}" if apt['description'] else ""
						text += f"{status_emoji} {start_time}-{end_time}: {apt['patient_name']} ({apt['patient_email']}){reason}\n"
					
					if stats.get('by_condition'):
						text += f"\n🏷️ **By Reason:** {', '.join(f'{k}: {v}' for k, v in stats['by_condition'].items())}"
				else:
					text += "📭 No appointments scheduled for this date."
				
				await _send_slack_message(channel, text)
				stats["slack_sent"] = True
		return stats


if __name__ == "__main__":
	mcp.run(transport="stdio") 
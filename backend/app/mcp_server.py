from __future__ import annotations

from datetime import datetime
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import SessionLocal
from .repositories import book_appointment, daily_stats, find_availability_slots, get_doctor_by_name, get_patient_by_email
from .schemas import BookAppointmentInput, DoctorAvailabilityQuery, DoctorAvailabilityResult, StatsQuery

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
async def check_doctor_availability(query: dict[str, Any]) -> dict[str, Any]:
	"""
	Check a doctor's availability for a given date and optional part of day.
	Args:
		query: {"doctor_name": str, "date": "YYYY-MM-DD", "part_of_day": str | None}
	Returns:
		{"doctor_id": int, "doctor_name": str, "available_slots": ["2025-08-14T09:00Z-09:30Z", ...]}
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
		slots = await find_availability_slots(db, doctor.id, payload.date, payload.part_of_day)
		formatted = [f"{s.isoformat()}Z-{e.isoformat()}Z" for s, e in slots]
		return DoctorAvailabilityResult(doctor_id=doctor.id, doctor_name=doctor.name, available_slots=formatted).model_dump()


@mcp.tool()
async def book_appointment_tool(data: dict[str, Any]) -> dict[str, Any]:
	"""
	Book an appointment if the slot is free, add to calendar, and send confirmation email.
	Args:
		{"doctor_name": str, "patient_email": str, "start_at": iso, "end_at": iso, "description": str | None}
	Returns:
		{"appointment_id": int, "calendar_event_id": str}
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
			body=f"Your appointment is scheduled from {payload.start_at} to {payload.end_at}.",
		)
		return {"appointment_id": appt.id, "calendar_event_id": event_id}


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
				text = (
					f"Appointment summary for {payload.for_date or datetime.now().date()}\n"
					f"Total: {stats['total_appointments']} | Completed: {stats['completed']} | Canceled: {stats['canceled']}\n"
					f"By condition: {stats.get('by_condition') or {}}"
				)
				await _send_slack_message(channel, text)
		return stats


if __name__ == "__main__":
	mcp.run(transport="stdio") 
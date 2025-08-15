from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from .models import Appointment, Doctor, DoctorAvailability, Patient


def _to_utc(dt: datetime) -> datetime:
	if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
		return dt.replace(tzinfo=timezone.utc)
	return dt.astimezone(timezone.utc)


def _same_instant(a: datetime, b: datetime) -> bool:
	return _to_utc(a) == _to_utc(b)


async def get_doctor_by_name(db: AsyncSession, doctor_name: str) -> Optional[Doctor]:
	stmt = select(Doctor).where(func.lower(Doctor.name) == doctor_name.lower())
	res = await db.execute(stmt)
	return res.scalar_one_or_none()


async def get_patient_by_email(db: AsyncSession, email: str) -> Optional[Patient]:
	stmt = select(Patient).where(func.lower(Patient.email) == email.lower())
	res = await db.execute(stmt)
	return res.scalar_one_or_none()


async def list_doctors(db: AsyncSession) -> list[Doctor]:
	stmt = select(Doctor).order_by(Doctor.name)
	res = await db.execute(stmt)
	return list(res.scalars().all())


async def find_availability_slots(
	db: AsyncSession,
	doctor_id: int,
	day: date,
	part_of_day: Optional[str] = None,
	slot_minutes: int = 30,
) -> list[tuple[datetime, datetime]]:
	weekday = day.weekday()
	avail_stmt = select(DoctorAvailability).where(DoctorAvailability.doctor_id == doctor_id, DoctorAvailability.day_of_week == weekday)
	avail = (await db.execute(avail_stmt)).scalars().all()
	if not avail:
		return []

	# Existing appointments
	start_day = datetime.combine(day, time(0, 0), tzinfo=timezone.utc)
	end_day = start_day + timedelta(days=1)
	appt_stmt = select(Appointment).where(
		Appointment.doctor_id == doctor_id,
		Appointment.start_at >= start_day,
		Appointment.start_at < end_day,
		Appointment.status != "canceled",
	)
	existing = (await db.execute(appt_stmt)).scalars().all()

	busy_blocks = [( _to_utc(a.start_at), _to_utc(a.end_at) ) for a in existing]

	def overlaps(a: datetime, b: datetime) -> bool:
		for s, e in busy_blocks:
			if a < e and b > s:
				return True
		return False

	results: list[tuple[datetime, datetime]] = []
	for a in avail:
		curr = datetime.combine(day, a.start_time, tzinfo=timezone.utc)
		end = datetime.combine(day, a.end_time, tzinfo=timezone.utc)
		while curr + timedelta(minutes=slot_minutes) <= end:
			next_t = curr + timedelta(minutes=slot_minutes)
			if part_of_day:
				if part_of_day == "morning" and not (time(6, 0) <= curr.time() < time(12, 0)):
					curr = next_t
					continue
				if part_of_day == "afternoon" and not (time(12, 0) <= curr.time() < time(17, 0)):
					curr = next_t
					continue
				if part_of_day == "evening" and not (time(17, 0) <= curr.time() <= time(21, 0)):
					curr = next_t
					continue
			if not overlaps(curr, next_t):
				results.append((curr, next_t))
			curr = next_t

	return results


async def book_appointment(
	db: AsyncSession,
	doctor: Doctor,
	patient: Patient,
	start_at: datetime,
	end_at: datetime,
	description: Optional[str] = None,
) -> Appointment:
	# Ensure UTC aware
	start_at = _to_utc(start_at)
	end_at = _to_utc(end_at)

	# Enforce that the requested slot matches the doctor's availability schedule
	requested_minutes = int((end_at - start_at).total_seconds() // 60)
	if requested_minutes <= 0:
		raise ValueError("Invalid time range")
	allowed = await find_availability_slots(db, doctor.id, start_at.date(), None, slot_minutes=requested_minutes)
	if not any(_same_instant(s, start_at) and _same_instant(e, end_at) for s, e in allowed):
		raise ValueError("Requested time is outside the doctor's availability or already taken")

	# Ensure no overlap (redundant with allowed check but kept defensive)
	conflict_stmt = select(func.count(Appointment.id)).where(
		Appointment.doctor_id == doctor.id,
		Appointment.status != "canceled",
		Appointment.start_at < end_at,
		Appointment.end_at > start_at,
	)
	conflicts = (await db.execute(conflict_stmt)).scalar_one()
	if conflicts:
		raise ValueError("Requested time overlaps with existing appointment")

	appt = Appointment(
		doctor_id=doctor.id,
		patient_id=patient.id,
		start_at=start_at,
		end_at=end_at,
		description=description,
		status="scheduled",
	)
	db.add(appt)
	await db.commit()
	await db.refresh(appt)
	return appt


async def get_appointment_by_id(db: AsyncSession, appointment_id: int) -> Optional[Appointment]:
	stmt = select(Appointment).where(Appointment.id == appointment_id)
	res = await db.execute(stmt)
	return res.scalar_one_or_none()


async def cancel_appointment(db: AsyncSession, appointment_id: int) -> Appointment:
	appt = await get_appointment_by_id(db, appointment_id)
	if not appt:
		raise ValueError("Appointment not found")
	appt.status = "canceled"
	await db.commit()
	await db.refresh(appt)
	return appt


async def cancel_appointments_by_date(
	db: AsyncSession,
	the_date: date,
	doctor_id: Optional[int] = None,
) -> list[Appointment]:
	"""Cancel all non-canceled appointments on a given date, optionally for a doctor."""
	start_day = datetime.combine(the_date, time(0, 0), tzinfo=timezone.utc)
	end_day = start_day + timedelta(days=1)
	where = [Appointment.start_at >= start_day, Appointment.start_at < end_day, Appointment.status != "canceled"]
	if doctor_id:
		where.append(Appointment.doctor_id == doctor_id)
	# Load with relationships for notifications
	stmt = select(Appointment).options(joinedload(Appointment.patient), joinedload(Appointment.doctor)).where(and_(*where))
	apps = (await db.execute(stmt)).scalars().all()
	for appt in apps:
		appt.status = "canceled"
	await db.commit()
	# Refresh objects to ensure updated status
	for appt in apps:
		await db.refresh(appt)
	return apps


async def list_appointments(
	db: AsyncSession,
	the_date: date,
	doctor_id: Optional[int] = None,
	patient_email: Optional[str] = None,
	at_time: Optional[time] = None,
) -> list[dict]:
	"""List appointments for a date, optionally filter by doctor, patient email, or a specific time."""
	start_day = datetime.combine(the_date, time(0, 0), tzinfo=timezone.utc)
	end_day = start_day + timedelta(days=1)
	conds = [Appointment.start_at >= start_day, Appointment.start_at < end_day]
	if doctor_id:
		conds.append(Appointment.doctor_id == doctor_id)
	if patient_email:
		conds.append(func.lower(Patient.email) == patient_email.lower())
	if at_time is not None:
		dt = datetime.combine(the_date, at_time, tzinfo=timezone.utc)
		conds.append(Appointment.start_at <= dt)
		conds.append(Appointment.end_at > dt)
	stmt = (
		select(Appointment, Doctor, Patient)
		.join(Doctor, Doctor.id == Appointment.doctor_id)
		.join(Patient, Patient.id == Appointment.patient_id)
		.where(and_(*conds))
		.order_by(Appointment.start_at)
	)
	rows = (await db.execute(stmt)).all()
	results: list[dict] = []
	for appt, doc, pat in rows:
		results.append({
			"appointment_id": appt.id,
			"start_at": _to_utc(appt.start_at).isoformat(),
			"end_at": _to_utc(appt.end_at).isoformat(),
			"status": appt.status,
			"doctor_name": doc.name,
			"doctor_email": doc.email,
			"patient_name": pat.name,
			"patient_email": pat.email,
			"description": appt.description or "",
		})
	return results


async def daily_stats(
	db: AsyncSession,
	the_date: date,
	doctor_id: Optional[int] = None,
	condition_like: Optional[str] = None,
) -> dict:
	start_day = datetime.combine(the_date, time(0, 0), tzinfo=timezone.utc)
	end_day = start_day + timedelta(days=1)

	where = [Appointment.start_at >= start_day, Appointment.start_at < end_day]
	if doctor_id:
		where.append(Appointment.doctor_id == doctor_id)

	base = select(Appointment).where(and_(*where))
	apps = (await db.execute(base)).scalars().all()

	total = len(apps)
	completed = len([a for a in apps if a.status == "completed"])
	canceled = len([a for a in apps if a.status == "canceled"])

	by_condition: dict[str, int] = {}
	if condition_like:
		# Count by reason (appointment description)
		pattern = f"%{condition_like.lower()}%"
		count_stmt = select(func.count(Appointment.id)).where(and_(*where, func.lower(func.coalesce(Appointment.description, "")).like(pattern)))
		count = (await db.execute(count_stmt)).scalar() or 0
		by_condition[condition_like] = count

	return {
		"total_appointments": total,
		"completed": completed,
		"canceled": canceled,
		"by_condition": by_condition or None,
	} 


async def patients_by_reason(
	db: AsyncSession,
	the_date: date,
	reason_like: str,
	doctor_id: Optional[int] = None,
) -> list[dict]:
	"""Return patients with appointments on the date where description contains reason_like (case-insensitive)."""
	start_day = datetime.combine(the_date, time(0, 0), tzinfo=timezone.utc)
	end_day = start_day + timedelta(days=1)
	conds = [Appointment.start_at >= start_day, Appointment.start_at < end_day, func.lower(func.coalesce(Appointment.description, "")).like(f"%{reason_like.lower()}%")]
	if doctor_id:
		conds.append(Appointment.doctor_id == doctor_id)
	stmt = (
		select(Appointment, Patient)
		.join(Patient, Patient.id == Appointment.patient_id)
		.where(and_(*conds))
		.order_by(Appointment.start_at)
	)
	rows = (await db.execute(stmt)).all()
	seen: set[int] = set()
	results: list[dict] = []
	for appt, pat in rows:
		if pat.id in seen:
			continue
		seen.add(pat.id)
		results.append({
			"patient_name": pat.name,
			"patient_email": pat.email,
			"appointment_id": appt.id,
			"start_at": _to_utc(appt.start_at).isoformat(),
			"end_at": _to_utc(appt.end_at).isoformat(),
		})
	return results 
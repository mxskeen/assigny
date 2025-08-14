from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Appointment, Doctor, DoctorAvailability, Patient


async def get_doctor_by_name(db: AsyncSession, doctor_name: str) -> Optional[Doctor]:
	stmt = select(Doctor).where(func.lower(Doctor.name) == doctor_name.lower())
	res = await db.execute(stmt)
	return res.scalar_one_or_none()


async def get_patient_by_email(db: AsyncSession, email: str) -> Optional[Patient]:
	stmt = select(Patient).where(func.lower(Patient.email) == email.lower())
	res = await db.execute(stmt)
	return res.scalar_one_or_none()


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
	start_day = datetime.combine(day, time(0, 0)).astimezone()
	end_day = start_day + timedelta(days=1)
	appt_stmt = select(Appointment).where(
		Appointment.doctor_id == doctor_id,
		Appointment.start_at >= start_day,
		Appointment.start_at < end_day,
		Appointment.status != "canceled",
	)
	existing = (await db.execute(appt_stmt)).scalars().all()

	busy_blocks = [(a.start_at, a.end_at) for a in existing]

	def overlaps(a: datetime, b: datetime) -> bool:
		for s, e in busy_blocks:
			if a < e and b > s:
				return True
		return False

	results: list[tuple[datetime, datetime]] = []
	for a in avail:
		curr = datetime.combine(day, a.start_time).astimezone()
		end = datetime.combine(day, a.end_time).astimezone()
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
	# Ensure no overlap
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


async def daily_stats(
	db: AsyncSession,
	the_date: date,
	doctor_id: Optional[int] = None,
	condition_like: Optional[str] = None,
) -> dict:
	start_day = datetime.combine(the_date, time(0, 0)).astimezone()
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
		# join with patient and count
		join_stmt = (
			select(func.count(Appointment.id))
			.join(Patient, Patient.id == Appointment.patient_id)
			.where(and_(*where, func.lower(Patient.primary_condition).like(f"%{condition_like.lower()}%")))
		)
		count = (await db.execute(join_stmt)).scalar() or 0
		by_condition[condition_like] = count

	return {
		"total_appointments": total,
		"completed": completed,
		"canceled": canceled,
		"by_condition": by_condition or None,
	} 
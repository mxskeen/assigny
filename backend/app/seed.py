from __future__ import annotations

import asyncio
from datetime import time

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from .db import SessionLocal
from .models import Doctor, DoctorAvailability, Patient


async def seed() -> None:
	async with SessionLocal() as db:  # type: AsyncSession
		# Doctor
		existing_dr = (await db.execute(select(Doctor).where(func.lower(Doctor.email) == "ahuja@example.com"))).scalar_one_or_none()
		if existing_dr is None:
			dr = Doctor(name="Dr. Ahuja", email="ahuja@example.com", specialty="General Physician")
			db.add(dr)
			await db.flush()
		else:
			dr = existing_dr
		# Patient
		existing_pt = (await db.execute(select(Patient).where(func.lower(Patient.email) == "john@example.com"))).scalar_one_or_none()
		if existing_pt is None:
			pt = Patient(name="John Doe", email="john@example.com", primary_condition="fever")
			db.add(pt)
			await db.flush()
		# Availability: Mon-Fri 9-12, 14-17 (ensure not duplicated)
		for d in range(0, 5):
			row_morning = (await db.execute(select(DoctorAvailability).where(DoctorAvailability.doctor_id == dr.id, DoctorAvailability.day_of_week == d, DoctorAvailability.start_time == time(9, 0)))).scalar_one_or_none()
			if row_morning is None:
				db.add(DoctorAvailability(doctor_id=dr.id, day_of_week=d, start_time=time(9, 0), end_time=time(12, 0)))
			row_afternoon = (await db.execute(select(DoctorAvailability).where(DoctorAvailability.doctor_id == dr.id, DoctorAvailability.day_of_week == d, DoctorAvailability.start_time == time(14, 0)))).scalar_one_or_none()
			if row_afternoon is None:
				db.add(DoctorAvailability(doctor_id=dr.id, day_of_week=d, start_time=time(14, 0), end_time=time(17, 0)))
		await db.commit()


if __name__ == "__main__":
	asyncio.run(seed())

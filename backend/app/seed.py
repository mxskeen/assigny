from __future__ import annotations

import asyncio
from datetime import time, datetime, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from .db import SessionLocal
from .models import Doctor, DoctorAvailability, Patient, Appointment


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

        # Patients with Indian names
        patients_data = [
            ("Priya Sharma", "priya.sharma@gmail.com", "fever"),
            ("Arjun Patel", "arjun.patel@gmail.com", "headache"),
            ("Sneha Gupta", "sneha.gupta@gmail.com", "fever"),
            ("Rahul Singh", "rahul.singh@gmail.com", "checkup"),
            ("Ananya Reddy", "ananya.reddy@gmail.com", "cough"),
            ("Vikram Kumar", "vikram.kumar@gmail.com", "back pain"),
        ]
        
        patients = []
        for name, email, condition in patients_data:
            existing_pt = (await db.execute(select(Patient).where(func.lower(Patient.email) == email.lower()))).scalar_one_or_none()
            if existing_pt is None:
                pt = Patient(name=name, email=email, primary_condition=condition)
                db.add(pt)
                await db.flush()
                patients.append(pt)
            else:
                patients.append(existing_pt)

        # Availability: Mon-Sun 9-12, 14-17 (ensure not duplicated)
        for d in range(0, 7):  # Include weekends (0=Mon, 6=Sun)
            row_morning = (await db.execute(select(DoctorAvailability).where(
                DoctorAvailability.doctor_id == dr.id, 
                DoctorAvailability.day_of_week == d, 
                DoctorAvailability.start_time == time(9, 0)
            ))).scalar_one_or_none()
            if row_morning is None:
                db.add(DoctorAvailability(doctor_id=dr.id, day_of_week=d, start_time=time(9, 0), end_time=time(12, 0)))
            
            row_afternoon = (await db.execute(select(DoctorAvailability).where(
                DoctorAvailability.doctor_id == dr.id, 
                DoctorAvailability.day_of_week == d, 
                DoctorAvailability.start_time == time(14, 0)
            ))).scalar_one_or_none()
            if row_afternoon is None:
                db.add(DoctorAvailability(doctor_id=dr.id, day_of_week=d, start_time=time(14, 0), end_time=time(17, 0)))

        # Create sample appointments for today
        today = datetime.now().date()
        today_start = datetime.combine(today, time(0, 0))
        
        # Check if appointments for today already exist
        existing_appts = (await db.execute(
            select(Appointment).where(
                Appointment.doctor_id == dr.id,
                Appointment.start_at >= today_start,
                Appointment.start_at < today_start + timedelta(days=1)
            )
        )).scalars().all()
        
        if not existing_appts and len(patients) >= 4:
            # Create sample appointments for today with Indian patients
            appointments_data = [
                (today_start.replace(hour=9, minute=30), today_start.replace(hour=10, minute=0), "fever", "scheduled"),
                (today_start.replace(hour=10, minute=30), today_start.replace(hour=11, minute=0), "headache", "scheduled"),
                (today_start.replace(hour=14, minute=0), today_start.replace(hour=14, minute=30), "fever", "completed"),
                (today_start.replace(hour=15, minute=0), today_start.replace(hour=15, minute=30), "checkup", "scheduled"),
                (today_start.replace(hour=16, minute=0), today_start.replace(hour=16, minute=30), "cough", "scheduled"),
            ]
            
            for i, (start_time, end_time, description, status) in enumerate(appointments_data):
                if i < len(patients):
                    appointment = Appointment(
                        doctor_id=dr.id,
                        patient_id=patients[i].id,
                        start_at=start_time,
                        end_at=end_time,
                        description=description,
                        status=status
                    )
                    db.add(appointment)

        await db.commit()
        print(f"Seeded database with {len(patients)} Indian patients and sample appointments for {today}")


if __name__ == "__main__":
    asyncio.run(seed())
 
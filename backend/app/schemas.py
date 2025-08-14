from __future__ import annotations

from datetime import datetime, time, date
from typing import Optional

from pydantic import BaseModel, EmailStr


class DoctorCreate(BaseModel):
	name: str
	email: EmailStr
	specialty: Optional[str] = None


class DoctorOut(BaseModel):
	id: int
	name: str
	email: EmailStr
	specialty: Optional[str] = None

	class Config:
		from_attributes = True


class PatientCreate(BaseModel):
	name: str
	email: EmailStr
	primary_condition: Optional[str] = None


class PatientOut(BaseModel):
	id: int
	name: str
	email: EmailStr
	primary_condition: Optional[str] = None

	class Config:
		from_attributes = True


class AvailabilitySlot(BaseModel):
	day_of_week: int
	start_time: time
	end_time: time


class AppointmentCreate(BaseModel):
	doctor_id: int
	patient_id: int
	start_at: datetime
	end_at: datetime
	description: Optional[str] = None


class AppointmentOut(BaseModel):
	id: int
	doctor_id: int
	patient_id: int
	start_at: datetime
	end_at: datetime
	status: str
	description: Optional[str] = None
	diagnosis: Optional[str] = None

	class Config:
		from_attributes = True


class DoctorAvailabilityQuery(BaseModel):
	doctor_name: str
	date: date
	part_of_day: Optional[str] = None  # morning/afternoon/evening


class DoctorAvailabilityResult(BaseModel):
	doctor_id: int
	doctor_name: str
	available_slots: list[str]


class BookAppointmentInput(BaseModel):
	doctor_name: str
	patient_email: EmailStr
	start_at: datetime
	end_at: datetime
	description: Optional[str] = None


class StatsQuery(BaseModel):
	for_date: Optional[date] = None
	doctor_name: Optional[str] = None
	condition_like: Optional[str] = None
	notify: Optional[bool] = None
	notify_channel: Optional[str] = None


class StatsResult(BaseModel):
	total_appointments: int
	completed: int
	canceled: int
	by_condition: dict[str, int] | None = None 
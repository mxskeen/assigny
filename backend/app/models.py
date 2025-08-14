from __future__ import annotations

from datetime import datetime, time
from typing import Optional

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, String, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Doctor(Base):
	__tablename__ = "doctors"

	id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
	name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
	email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
	specialty: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

	appointments: Mapped[list[Appointment]] = relationship(back_populates="doctor", cascade="all, delete-orphan")


class Patient(Base):
	__tablename__ = "patients"

	id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
	name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
	email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
	primary_condition: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

	appointments: Mapped[list[Appointment]] = relationship(back_populates="patient", cascade="all, delete-orphan")


class DoctorAvailability(Base):
	__tablename__ = "doctor_availability"
	__table_args__ = (
		UniqueConstraint("doctor_id", "day_of_week", "start_time", name="uix_doctor_slot"),
	)

	id: Mapped[int] = mapped_column(Integer, primary_key=True)
	doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id", ondelete="CASCADE"), index=True)
	day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=Mon ... 6=Sun
	start_time: Mapped[time] = mapped_column(Time, nullable=False)
	end_time: Mapped[time] = mapped_column(Time, nullable=False)

	doctor: Mapped[Doctor] = relationship(backref="availability")


class Appointment(Base):
	__tablename__ = "appointments"
	__table_args__ = (
		UniqueConstraint("doctor_id", "start_at", name="uix_doctor_start"),
	)

	id: Mapped[int] = mapped_column(Integer, primary_key=True)
	doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id", ondelete="CASCADE"), index=True)
	patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
	start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
	end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
	status: Mapped[str] = mapped_column(String(50), default="scheduled")  # scheduled, canceled, completed
	description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
	diagnosis: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

	doctor: Mapped[Doctor] = relationship(back_populates="appointments")
	patient: Mapped[Patient] = relationship(back_populates="appointments") 
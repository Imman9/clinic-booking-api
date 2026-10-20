from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.config import settings
from app.exceptions import conflict, invalid, not_found
from app.models import Appointment, Doctor, Patient, WorkingHour

UTC = timezone.utc

def as_utc(value: datetime) -> datetime:
    # SQLite drops timezone metadata; stored appointment values are normalized UTC.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

def clinic_zone():
    try: return ZoneInfo(settings.clinic_timezone)
    except ZoneInfoNotFoundError: raise RuntimeError(f"Invalid CLINIC_TIMEZONE: {settings.clinic_timezone}")

def normalize_start(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise invalid("TIMEZONE_REQUIRED", "start_time must include a timezone offset.")
    if value.second or value.microsecond or value.minute not in (0, 30):
        raise invalid("INVALID_SLOT", "Appointments must start on a 30-minute boundary.")
    return value.astimezone(UTC)

def validate_target(db: Session, doctor: Doctor, start: datetime, exclude_id: int | None = None) -> datetime:
    start = normalize_start(start)
    now = datetime.now(UTC)
    if start < now: raise invalid("PAST_APPOINTMENT", "Appointment cannot be in the past.")
    if start < now + timedelta(minutes=settings.booking_buffer_minutes):
        raise invalid("BOOKING_TOO_SOON", f"Appointments must be booked at least {settings.booking_buffer_minutes} minutes ahead.")
    local = start.astimezone(clinic_zone())
    hours = db.scalars(select(WorkingHour).where(WorkingHour.doctor_id == doctor.id, WorkingHour.day_of_week == local.weekday())).all()
    slot_start = local.time().replace(tzinfo=None)
    slot_end = (local + timedelta(minutes=30)).time().replace(tzinfo=None)
    if not any(h.start_time <= slot_start and slot_end <= h.end_time for h in hours):
        raise invalid("OUTSIDE_WORKING_HOURS", "The selected slot is outside the doctor's working hours.")
    query = select(Appointment).where(Appointment.doctor_id == doctor.id, Appointment.start_time == start, Appointment.status == "BOOKED")
    if exclude_id is not None: query = query.where(Appointment.id != exclude_id)
    if db.scalar(query) is not None: raise conflict("SLOT_TAKEN", "The selected slot is already booked.")
    return start

def create_appointment(db: Session, doctor_id: int, patient_id: int, value: datetime) -> Appointment:
    doctor, patient = db.get(Doctor, doctor_id), db.get(Patient, patient_id)
    if not doctor: raise not_found("Doctor")
    if not patient: raise not_found("Patient")
    start = validate_target(db, doctor, value)
    appt = Appointment(doctor_id=doctor_id, patient_id=patient_id, start_time=start, end_time=start + timedelta(minutes=30))
    db.add(appt)
    try: db.commit()
    except IntegrityError:
        db.rollback(); raise conflict("SLOT_TAKEN", "The selected slot is already booked.")
    db.refresh(appt)
    return appt

def cancel_appointment(db: Session, appointment_id: int, reason: str) -> Appointment:
    appt = db.get(Appointment, appointment_id)
    if not appt: raise not_found("Appointment")
    if appt.status == "CANCELLED": raise conflict("ALREADY_CANCELLED", "Appointment has already been cancelled.")
    if not reason.strip(): raise invalid("REASON_REQUIRED", "A cancellation reason is required.")
    appt.status, appt.cancel_reason, appt.cancelled_at = "CANCELLED", reason.strip(), datetime.now(UTC)
    db.commit(); db.refresh(appt)
    return appt

def reschedule_appointment(db: Session, appointment_id: int, value: datetime) -> Appointment:
    appt = db.get(Appointment, appointment_id)
    if not appt: raise not_found("Appointment")
    if appt.status == "CANCELLED": raise conflict("ALREADY_CANCELLED", "A cancelled appointment cannot be rescheduled.")
    start = normalize_start(value)
    if start == as_utc(appt.start_time): raise invalid("NO_OP_RESCHEDULE", "The new slot must differ from the current slot.")
    doctor = db.get(Doctor, appt.doctor_id)
    start = validate_target(db, doctor, value, exclude_id=appt.id)
    appt.start_time, appt.end_time = start, start + timedelta(minutes=30)
    try: db.commit()
    except IntegrityError:
        db.rollback(); raise conflict("SLOT_TAKEN", "The selected slot is already booked.")
    db.refresh(appt)
    return appt

def availability(db: Session, doctor_id: int, day: date) -> list[tuple[datetime, datetime]]:
    doctor = db.get(Doctor, doctor_id)
    if not doctor: raise not_found("Doctor")
    zone = clinic_zone()
    local_start = datetime.combine(day, time.min, tzinfo=zone)
    local_end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)
    occupied = {as_utc(value) for value in db.scalars(select(Appointment.start_time).where(Appointment.doctor_id == doctor_id, Appointment.status == "BOOKED", Appointment.start_time >= local_start.astimezone(UTC), Appointment.start_time < local_end.astimezone(UTC))).all()}
    cutoff = datetime.now(UTC) + timedelta(minutes=settings.booking_buffer_minutes)
    blocks = db.scalars(select(WorkingHour).where(WorkingHour.doctor_id == doctor_id, WorkingHour.day_of_week == day.weekday()).order_by(WorkingHour.start_time)).all()
    result = []
    for block in blocks:
        cursor = datetime.combine(day, block.start_time, tzinfo=zone)
        end = datetime.combine(day, block.end_time, tzinfo=zone)
        while cursor + timedelta(minutes=30) <= end:
            start_utc = cursor.astimezone(UTC)
            if start_utc >= cutoff and start_utc not in occupied:
                result.append((cursor, cursor + timedelta(minutes=30)))
            cursor += timedelta(minutes=30)
    return result

def patient_appointments(db: Session, patient_id: int) -> list[Appointment]:
    if not db.get(Patient, patient_id): raise not_found("Patient")
    return db.scalars(select(Appointment).where(Appointment.patient_id == patient_id, Appointment.status == "BOOKED", Appointment.start_time >= datetime.now(UTC)).order_by(Appointment.start_time)).all()

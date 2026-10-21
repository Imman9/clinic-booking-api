from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from pydantic import BaseModel, ConfigDict, Field, field_serializer
from app.config import settings


class BookingCreate(BaseModel):
    doctor_id: int
    patient_id: int
    start_time: datetime


class RescheduleRequest(BaseModel):
    new_start_time: datetime


class CancelRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class AppointmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doctor_id: int
    patient_id: int
    start_time: datetime
    end_time: datetime
    status: str
    cancel_reason: str | None = None

    @field_serializer("start_time", "end_time")
    def serialize_appointment_times(self, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(ZoneInfo(settings.clinic_timezone))


class SlotOut(BaseModel):
    start_time: datetime
    end_time: datetime


class AvailabilityOut(BaseModel):
    doctor_id: int
    date: date
    available_slots: list[SlotOut]

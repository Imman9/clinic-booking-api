from datetime import date, datetime
from pydantic import BaseModel, ConfigDict, Field


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


class SlotOut(BaseModel):
    start_time: datetime
    end_time: datetime


class AvailabilityOut(BaseModel):
    doctor_id: int
    date: date
    available_slots: list[SlotOut]

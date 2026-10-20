from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import AppointmentOut, BookingCreate, CancelRequest, RescheduleRequest
from app.services.appointments import cancel_appointment, create_appointment, reschedule_appointment

router = APIRouter(tags=["appointments"])

@router.post("/appointments", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED)
def book(payload: BookingCreate, db: Session = Depends(get_db)):
    return create_appointment(db, payload.doctor_id, payload.patient_id, payload.start_time)

@router.patch("/appointments/{appointment_id}/cancel", response_model=AppointmentOut)
def cancel(appointment_id: int, payload: CancelRequest, db: Session = Depends(get_db)):
    return cancel_appointment(db, appointment_id, payload.reason)

@router.patch("/appointments/{appointment_id}/reschedule", response_model=AppointmentOut)
def reschedule(appointment_id: int, payload: RescheduleRequest, db: Session = Depends(get_db)):
    return reschedule_appointment(db, appointment_id, payload.new_start_time)

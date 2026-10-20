from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import AppointmentOut
from app.services.appointments import patient_appointments

router = APIRouter(tags=["patients"])

@router.get("/patients/{patient_id}/appointments", response_model=list[AppointmentOut])
def get_patient_appointments(patient_id: int, db: Session = Depends(get_db)):
    return patient_appointments(db, patient_id)

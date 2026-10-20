from datetime import date
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import AvailabilityOut, SlotOut
from app.services.appointments import availability

router = APIRouter(tags=["doctors"])

@router.get("/doctors/{doctor_id}/availability", response_model=AvailabilityOut)
def get_availability(doctor_id: int, date: date, db: Session = Depends(get_db)):
    return AvailabilityOut(doctor_id=doctor_id, date=date, available_slots=[SlotOut(start_time=s, end_time=e) for s, e in availability(db, doctor_id, date)])

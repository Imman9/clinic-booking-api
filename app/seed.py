from datetime import time
from app.database import SessionLocal
from app.models import Doctor, Patient, WorkingHour

DOCTORS = [
    ("Dr. Achieng", "General Practice"), ("Dr. Mwangi", "Paediatrics"),
    ("Dr. Njoroge", "Cardiology"), ("Dr. Wanjiku", "Dermatology"),
    ("Dr. Otieno", "Family Medicine"),
]

def seed():
    with SessionLocal() as db:
        if db.query(Doctor).count(): return
        for name, specialization in DOCTORS:
            doctor = Doctor(name=name, specialization=specialization)
            doctor.working_hours = [WorkingHour(day_of_week=d, start_time=time(9), end_time=time(17)) for d in range(5)]
            db.add(doctor)
        db.add_all([Patient(name="Sample Patient", contact="patient@example.com"), Patient(name="Alex Kimani", contact="+254700000001")])
        db.commit()

if __name__ == "__main__": seed()

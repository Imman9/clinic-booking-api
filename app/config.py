import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./clinic.db")
    clinic_timezone: str = os.getenv("CLINIC_TIMEZONE", "Africa/Nairobi")
    booking_buffer_minutes: int = int(os.getenv("BOOKING_BUFFER_MINUTES", "60"))

settings = Settings()

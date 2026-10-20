
from datetime import time
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app
from app.models import Base, Doctor, Patient, WorkingHour


@pytest.fixture
def client():
    test_url = os.getenv("TEST_DATABASE_URL", "sqlite://")

    options = (
        {
            "connect_args": {"check_same_thread": False},
            "poolclass": StaticPool,
        }
        if test_url.startswith("sqlite")
        else {}
    )

    engine = create_engine(test_url, **options)
    testing_session = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )

    try:
        Base.metadata.create_all(engine)

        with testing_session() as db:
            doctor = Doctor(
                name="Dr. Achieng",
                specialization="General Practice",
            )
            doctor.working_hours = [
                WorkingHour(
                    day_of_week=day,
                    start_time=time(0),
                    end_time=time(23, 59),
                )
                for day in range(7)
            ]

            db.add_all([
                doctor,
                Patient(
                    name="Sam Patient",
                    contact="sam@example.com",
                ),
            ])
            db.commit()

        def override_get_db():
            with testing_session() as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db

        with TestClient(app) as test_client:
            yield test_client

    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(engine)
        engine.dispose()

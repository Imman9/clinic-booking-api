
from datetime import time
import os
from pathlib import Path

from alembic import command
from alembic.config import Config

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import app
from app.models import Base, Doctor, Patient, WorkingHour


@pytest.fixture(scope="session")
def test_engine():
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

    if not test_url.startswith("sqlite"):
        # Exercise the same schema and partial index that production gets.
        os.environ["MIGRATION_DATABASE_URL"] = test_url
        try:
            config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            command.upgrade(config, "head")
        finally:
            os.environ.pop("MIGRATION_DATABASE_URL", None)
    else:
        Base.metadata.create_all(engine)

    yield engine
    if test_url.startswith("sqlite"):
        Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(test_engine):
    test_url = os.getenv("TEST_DATABASE_URL", "sqlite://")
    engine = test_engine
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    try:
        with testing_session() as db:
            if test_url.startswith("sqlite"):
                for table in reversed(Base.metadata.sorted_tables):
                    db.execute(table.delete())
            else:
                db.execute(text("TRUNCATE TABLE appointments, working_hours, patients, doctors RESTART IDENTITY CASCADE"))
            db.commit()

        with testing_session() as db:
            doctor = Doctor(
                name="Dr. Achieng",
                specialization="General Practice",
            )
            doctor.working_hours = [
                WorkingHour(
                    day_of_week=day,
                    start_time=time(9),
                    end_time=time(17),
                )
                for day in range(5)
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

        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client

    finally:
        app.dependency_overrides.pop(get_db, None)

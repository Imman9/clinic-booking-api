from datetime import datetime, timedelta

import app.services.appointments as appointments_service
from tests.helpers import CLINIC_TZ, as_datetime, future_weekday, future_weekend


def test_availability_returns_clinic_local_half_hour_slots(client):
    day = future_weekday().date()

    response = client.get("/doctors/1/availability", params={"date": day.isoformat()})

    assert response.status_code == 200
    data = response.json()
    assert data["doctor_id"] == 1
    assert data["date"] == day.isoformat()
    starts = [datetime.fromisoformat(slot["start_time"]) for slot in data["available_slots"]]
    assert len(starts) == 16
    assert starts[0].hour == 9 and starts[0].minute == 0
    assert starts[-1].hour == 16 and starts[-1].minute == 30
    assert all(start.utcoffset().total_seconds() == 3 * 60 * 60 for start in starts)
    assert all(start.minute in (0, 30) for start in starts)


def test_availability_excludes_booked_slot(client):
    start = future_weekday(hour=10, minute=30)
    booked = client.post(
        "/appointments",
        json={"doctor_id": 1, "patient_id": 1, "start_time": start.isoformat()},
    )
    assert booked.status_code == 201

    response = client.get(
        "/doctors/1/availability",
        params={"date": start.date().isoformat()},
    )

    available_starts = [
        as_datetime(slot["start_time"]).timestamp()
        for slot in response.json()["available_slots"]
    ]
    assert start.timestamp() not in available_starts


def test_availability_is_empty_on_weekend(client):
    day = future_weekend()

    response = client.get("/doctors/1/availability", params={"date": day.isoformat()})

    assert response.status_code == 200
    assert response.json()["available_slots"] == []


def test_availability_excludes_past_and_buffered_slots(client, monkeypatch):
    fixed_now = datetime(2026, 10, 26, 10, 15, tzinfo=CLINIC_TZ)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is None else fixed_now.astimezone(tz)

    monkeypatch.setattr(appointments_service, "datetime", FrozenDateTime)
    response = client.get("/doctors/1/availability", params={"date": "2026-10-26"})

    assert response.status_code == 200
    starts = [datetime.fromisoformat(slot["start_time"]) for slot in response.json()["available_slots"]]
    assert starts
    assert starts[0].hour == 11 and starts[0].minute == 30
    assert all(start >= fixed_now + timedelta(minutes=60) for start in starts)


def test_availability_unknown_doctor_returns_404(client):
    response = client.get(
        "/doctors/999/availability",
        params={"date": future_weekday().date().isoformat()},
    )

    assert response.status_code == 404

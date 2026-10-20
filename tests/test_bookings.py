from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
from sqlalchemy import event
from sqlalchemy.orm import Session

def slot(offset_days=3):
    target = datetime.now(timezone.utc) + timedelta(days=offset_days)
    target = target.replace(hour=12, minute=0, second=0, microsecond=0)
    return target.isoformat()

def test_book_slot_and_prevent_double_booking(client):
    payload = {"doctor_id": 1, "patient_id": 1, "start_time": slot()}
    created = client.post("/appointments", json=payload)
    assert created.status_code == 201
    conflict = client.post("/appointments", json=payload)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "SLOT_TAKEN"

def test_cancel_releases_slot_and_repeat_cancel_conflicts(client):
    created = client.post("/appointments", json={"doctor_id": 1, "patient_id": 1, "start_time": slot()})
    appointment_id = created.json()["id"]
    cancelled = client.patch(f"/appointments/{appointment_id}/cancel", json={"reason": "Patient request"})
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    again = client.patch(f"/appointments/{appointment_id}/cancel", json={"reason": "Again"})
    assert again.status_code == 409

def test_naive_datetime_is_rejected(client):
    result = client.post("/appointments", json={"doctor_id": 1, "patient_id": 1, "start_time": "2099-01-05T12:00:00"})
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "TIMEZONE_REQUIRED"

def test_concurrent_bookings_for_same_slot_only_allow_one(client):
    test_database = os.getenv("TEST_DATABASE_URL", "sqlite://")
    if not test_database.startswith(("postgresql://", "postgresql+")):
        import pytest
        pytest.skip("Concurrency guarantee requires PostgreSQL; set TEST_DATABASE_URL to a disposable PostgreSQL database.")

    # Hold both requests immediately before commit so both pass the friendly
    # availability check and the database unique index must resolve the race.
    commit_barrier = Barrier(2, timeout=10)

    def wait_for_other_booking(session):
        commit_barrier.wait()

    event.listen(Session, "before_commit", wait_for_other_booking)
    payload = {"doctor_id": 1, "patient_id": 1, "start_time": slot()}
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(client.post, "/appointments", json=payload) for _ in range(2)]
            responses = [future.result(timeout=20) for future in futures]
    finally:
        event.remove(Session, "before_commit", wait_for_other_booking)

    assert sorted(response.status_code for response in responses) == [201, 409]
    loser = next(response for response in responses if response.status_code == 409)
    assert loser.json()["error"]["code"] == "SLOT_TAKEN"

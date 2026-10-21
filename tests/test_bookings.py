from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from tests.helpers import future_weekday, past_datetime, soon_datetime


def booking_payload(start_time=None, **overrides):
    payload = {
        "doctor_id": 1,
        "patient_id": 1,
        "start_time": (start_time or future_weekday()).isoformat(),
    }
    payload.update(overrides)
    return payload


def test_book_slot_and_prevent_double_booking(client):
    payload = booking_payload()
    created = client.post("/appointments", json=payload)
    assert created.status_code == 201

    conflict = client.post("/appointments", json=payload)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "SLOT_TAKEN"


def test_booking_outside_working_hours_is_rejected(client):
    outside_hours = future_weekday(hour=8)
    response = client.post("/appointments", json=booking_payload(outside_hours))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "OUTSIDE_WORKING_HOURS"


def test_booking_in_the_past_is_rejected(client):
    response = client.post("/appointments", json=booking_payload(past_datetime()))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PAST_APPOINTMENT"


def test_booking_inside_lead_time_buffer_is_rejected(client):
    response = client.post("/appointments", json=booking_payload(soon_datetime()))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "BOOKING_TOO_SOON"


def test_booking_off_the_half_hour_grid_is_rejected(client):
    response = client.post(
        "/appointments",
        json=booking_payload(future_weekday(hour=9, minute=15)),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_SLOT"


def test_booking_with_naive_datetime_is_rejected(client):
    response = client.post(
        "/appointments",
        json={"doctor_id": 1, "patient_id": 1, "start_time": "2099-01-05T12:00:00"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "TIMEZONE_REQUIRED"


@pytest.mark.parametrize(
    ("payload", "expected_message"),
    [
        ({"doctor_id": 999, "patient_id": 1}, "Doctor not found."),
        ({"doctor_id": 1, "patient_id": 999}, "Patient not found."),
    ],
)
def test_booking_unknown_doctor_or_patient_is_rejected(client, payload, expected_message):
    response = client.post(
        "/appointments",
        json={**booking_payload(), **payload},
    )

    assert response.status_code == 404
    assert response.json()["error"]["message"] == expected_message


def test_cancel_releases_slot_so_it_can_be_booked_again(client):
    payload = booking_payload()
    created = client.post("/appointments", json=payload)
    assert created.status_code == 201
    appointment_id = created.json()["id"]

    cancelled = client.patch(
        f"/appointments/{appointment_id}/cancel",
        json={"reason": "Patient request"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"

    rebooked = client.post("/appointments", json=payload)
    assert rebooked.status_code == 201
    assert rebooked.json()["status"] == "BOOKED"
    assert rebooked.json()["id"] != appointment_id

    repeated_cancel = client.patch(
        f"/appointments/{appointment_id}/cancel",
        json={"reason": "Again"},
    )
    assert repeated_cancel.status_code == 409
    assert repeated_cancel.json()["error"]["code"] == "ALREADY_CANCELLED"


def test_cancel_requires_a_nonblank_reason(client):
    appointment = client.post("/appointments", json=booking_payload()).json()

    missing = client.patch(f"/appointments/{appointment['id']}/cancel", json={})
    assert missing.status_code == 422

    blank = client.patch(
        f"/appointments/{appointment['id']}/cancel",
        json={"reason": "   "},
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["code"] == "REASON_REQUIRED"


def test_concurrent_bookings_for_same_slot_only_allow_one(client):
    test_database = os.getenv("TEST_DATABASE_URL", "sqlite://")
    if not test_database.startswith(("postgresql://", "postgresql+")):
        pytest.skip("Concurrency guarantee requires PostgreSQL; set TEST_DATABASE_URL to a disposable PostgreSQL database.")

    # Both requests pass the availability query before they race to commit.
    commit_barrier = Barrier(2, timeout=10)

    def wait_for_other_booking(session):
        commit_barrier.wait()

    event.listen(Session, "before_commit", wait_for_other_booking)
    payload = booking_payload()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(client.post, "/appointments", json=payload) for _ in range(2)]
            responses = [future.result(timeout=20) for future in futures]
    finally:
        event.remove(Session, "before_commit", wait_for_other_booking)

    assert sorted(response.status_code for response in responses) == [201, 409]
    loser = next(response for response in responses if response.status_code == 409)
    assert loser.json()["error"]["code"] == "SLOT_TAKEN"

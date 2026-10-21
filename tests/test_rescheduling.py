from datetime import datetime

import pytest

from tests.helpers import as_datetime, future_weekday, past_datetime, soon_datetime


def create_booking(client, start):
    response = client.post(
        "/appointments",
        json={
            "doctor_id": 1,
            "patient_id": 1,
            "start_time": start.isoformat(),
        },
    )
    assert response.status_code == 201
    return response.json()


def test_reschedule_moves_appointment_and_frees_original_slot(client):
    original_start = future_weekday(hour=9)
    destination = future_weekday(hour=11)
    appointment = create_booking(client, original_start)

    response = client.patch(
        f"/appointments/{appointment['id']}/reschedule",
        json={"new_start_time": destination.isoformat()},
    )

    assert response.status_code == 200
    assert response.json()["id"] == appointment["id"]
    assert as_datetime(response.json()["start_time"]).timestamp() == destination.timestamp()

    availability = client.get(
        "/doctors/1/availability",
        params={"date": original_start.date().isoformat()},
    )
    starts = [slot["start_time"] for slot in availability.json()["available_slots"]]
    assert any(as_datetime(value).timestamp() == original_start.timestamp() for value in starts)
    assert not any(as_datetime(value).timestamp() == destination.timestamp() for value in starts)


def test_reschedule_to_taken_slot_keeps_original_booking(client):
    original = create_booking(client, future_weekday(hour=9))
    destination = future_weekday(hour=11)
    occupied = create_booking(client, destination)

    response = client.patch(
        f"/appointments/{original['id']}/reschedule",
        json={"new_start_time": destination.isoformat()},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SLOT_TAKEN"
    appointments = client.get("/patients/1/appointments").json()
    by_id = {appointment["id"]: appointment for appointment in appointments}
    assert as_datetime(by_id[original["id"]]["start_time"]).timestamp() == as_datetime(original["start_time"]).timestamp()
    assert as_datetime(by_id[occupied["id"]]["start_time"]).timestamp() == as_datetime(occupied["start_time"]).timestamp()


def test_reschedule_to_same_slot_is_rejected(client):
    original_start = future_weekday(hour=9)
    appointment = create_booking(client, original_start)

    response = client.patch(
        f"/appointments/{appointment['id']}/reschedule",
        json={"new_start_time": original_start.isoformat()},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "NO_OP_RESCHEDULE"


def test_cancelled_appointment_cannot_be_rescheduled(client):
    appointment = create_booking(client, future_weekday(hour=9))
    client.patch(
        f"/appointments/{appointment['id']}/cancel",
        json={"reason": "Patient request"},
    )

    response = client.patch(
        f"/appointments/{appointment['id']}/reschedule",
        json={"new_start_time": future_weekday(hour=11).isoformat()},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ALREADY_CANCELLED"


def test_reschedule_unknown_appointment_returns_404(client):
    response = client.patch(
        "/appointments/999/reschedule",
        json={"new_start_time": future_weekday(hour=11).isoformat()},
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("target", "expected_code"),
    [
        (lambda: future_weekday(hour=8), "OUTSIDE_WORKING_HOURS"),
        (past_datetime, "PAST_APPOINTMENT"),
        (soon_datetime, "BOOKING_TOO_SOON"),
        (lambda: future_weekday(hour=9, minute=15), "INVALID_SLOT"),
        (lambda: datetime(2099, 1, 5, 12, 0), "TIMEZONE_REQUIRED"),
    ],
    ids=["outside-hours", "past", "inside-buffer", "off-grid", "timezone-required"],
)
def test_reschedule_target_uses_fresh_booking_validation(client, target, expected_code):
    original_start = future_weekday(hour=9)
    appointment = create_booking(client, original_start)

    response = client.patch(
        f"/appointments/{appointment['id']}/reschedule",
        json={"new_start_time": target().isoformat()},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == expected_code
    current = client.get("/patients/1/appointments").json()
    persisted = next(item for item in current if item["id"] == appointment["id"])
    assert as_datetime(persisted["start_time"]).timestamp() == as_datetime(appointment["start_time"]).timestamp()

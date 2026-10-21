from datetime import datetime

from tests.helpers import as_datetime, future_weekday


def create_booking(client, hour):
    start = future_weekday(hour=hour)
    response = client.post(
        "/appointments",
        json={"doctor_id": 1, "patient_id": 1, "start_time": start.isoformat()},
    )
    assert response.status_code == 201
    return response.json()


def test_patient_appointments_are_upcoming_sorted_and_exclude_cancelled(client):
    later = create_booking(client, 11)
    cancelled = create_booking(client, 10)
    earlier = create_booking(client, 9)
    cancellation = client.patch(
        f"/appointments/{cancelled['id']}/cancel",
        json={"reason": "Patient request"},
    )
    assert cancellation.status_code == 200

    response = client.get("/patients/1/appointments")

    assert response.status_code == 200
    appointments = response.json()
    ids = [appointment["id"] for appointment in appointments]
    assert ids == [earlier["id"], later["id"]]
    starts = [as_datetime(appointment["start_time"]) for appointment in appointments]
    assert starts == sorted(starts)
    assert all(start > datetime.now().astimezone() for start in starts)


def test_patient_without_appointments_receives_empty_list(client):
    response = client.get("/patients/1/appointments")

    assert response.status_code == 200
    assert response.json() == []


def test_unknown_patient_appointments_returns_404(client):
    response = client.get("/patients/999/appointments")

    assert response.status_code == 404

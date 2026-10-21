def test_unknown_route_uses_standard_error_shape(client):
    response = client.get("/route-that-does-not-exist")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "The requested resource was not found.",
        }
    }


def test_method_not_allowed_uses_standard_error_shape(client):
    response = client.post("/health")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"
    assert "message" in response.json()["error"]


def test_unexpected_error_returns_generic_safe_message(client, monkeypatch):
    def fail_availability(*args, **kwargs):
        raise RuntimeError("sensitive internal detail")

    monkeypatch.setattr("app.routers.doctors.availability", fail_availability)
    response = client.get("/doctors/1/availability?date=2099-01-05")

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected server error occurred.",
        }
    }
    assert "sensitive internal detail" not in response.text

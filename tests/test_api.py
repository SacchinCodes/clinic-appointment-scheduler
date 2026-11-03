import pytest
from fastapi.testclient import TestClient

from app.main import app, get_scheduler
from app.services import Scheduler
from tests.conftest import FIXED_NOW


@pytest.fixture
def client(tmp_path):
    sched = Scheduler(str(tmp_path / "api.db"), clock=lambda: FIXED_NOW)
    app.dependency_overrides[get_scheduler] = lambda: sched
    yield TestClient(app)
    app.dependency_overrides.clear()


PAYLOAD = {"doctor_id": 1, "patient_name": "Asha Rao", "patient_phone": "9876543210",
           "start_time": "2026-11-03T10:00:00", "duration_min": 30}


def test_full_flow(client):
    assert client.post("/doctors", json={"name": "Dr. API", "specialty": "General"}).status_code == 201
    assert client.post("/appointments", json=PAYLOAD).status_code == 201
    assert client.post("/appointments", json=PAYLOAD).status_code == 409   # double booking
    r = client.get("/doctors/1/availability", params={"day": "2026-11-03"})
    assert "10:00" not in r.json()["slots"]
    assert client.post("/appointments/1/cancel").json()["status"] == "cancelled"
    assert client.get("/stats").json()["cancelled"] == 1


def test_validation_errors(client):
    client.post("/doctors", json={"name": "Dr. API", "specialty": "General"})
    assert client.post("/appointments", json={**PAYLOAD, "start_time": "2026-11-07T10:00:00"}).status_code == 422
    assert client.post("/appointments", json={**PAYLOAD, "doctor_id": 42}).status_code == 404

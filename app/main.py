"""FastAPI REST layer. Interactive docs are served at /docs."""
from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any, Optional

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.services import ConflictError, NotFoundError, Scheduler, SchedulingError, ValidationError

app = FastAPI(
    title="Clinic Appointment Scheduler",
    description="REST API for booking appointments with double-booking prevention.",
    version="1.0.0",
)
_scheduler: Optional[Scheduler] = None


def get_scheduler() -> Scheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler(os.getenv("CLINIC_DB", "clinic.db"))
    return _scheduler


class DoctorIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    specialty: str = Field(min_length=2, max_length=80)


class AppointmentIn(BaseModel):
    doctor_id: int
    patient_name: str = Field(min_length=2, max_length=80)
    patient_phone: str
    start_time: datetime
    duration_min: int = 30
    reason: Optional[str] = Field(default=None, max_length=200)


@app.exception_handler(SchedulingError)
async def domain_error_handler(_: Request, exc: SchedulingError) -> JSONResponse:
    status = {NotFoundError: 404, ConflictError: 409, ValidationError: 422}.get(type(exc), 400)
    return JSONResponse(status_code=status, content={"detail": str(exc)})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/doctors", status_code=201)
def create_doctor(body: DoctorIn, s: Scheduler = Depends(get_scheduler)) -> dict[str, Any]:
    return s.add_doctor(body.name, body.specialty)


@app.get("/doctors")
def list_doctors(s: Scheduler = Depends(get_scheduler)) -> list[dict[str, Any]]:
    return s.list_doctors()


@app.post("/appointments", status_code=201)
def book(body: AppointmentIn, s: Scheduler = Depends(get_scheduler)) -> dict[str, Any]:
    return s.book(body.doctor_id, body.patient_name, body.patient_phone,
                  body.start_time, body.duration_min, body.reason)


@app.get("/appointments")
def list_appointments(
    day: Optional[date] = None,
    doctor_id: Optional[int] = None,
    status: Optional[str] = Query(default=None, pattern="^(booked|cancelled)$"),
    s: Scheduler = Depends(get_scheduler),
) -> list[dict[str, Any]]:
    return s.list_appointments(day, doctor_id, status)


@app.post("/appointments/{appointment_id}/cancel")
def cancel(appointment_id: int, s: Scheduler = Depends(get_scheduler)) -> dict[str, Any]:
    return s.cancel(appointment_id)


@app.get("/doctors/{doctor_id}/availability")
def availability(doctor_id: int, day: date, duration_min: int = 30,
                 s: Scheduler = Depends(get_scheduler)) -> dict[str, Any]:
    return {"doctor_id": doctor_id, "date": day, "slots": s.available_slots(doctor_id, day, duration_min)}


@app.get("/stats")
def stats(s: Scheduler = Depends(get_scheduler)) -> dict[str, Any]:
    return s.stats()

"""Business logic for the clinic scheduler (framework-independent, fully testable)."""
from __future__ import annotations

import re
import sqlite3
from collections import Counter
from datetime import date, datetime, time, timedelta
from typing import Any, Callable, Optional

OPEN_TIME = time(9, 0)
CLOSE_TIME = time(17, 0)
SLOT_MINUTES = 15
MAX_DURATION_MIN = 120
PHONE_RE = re.compile(r"^\+?\d{10,13}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS doctors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    specialty TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor_id INTEGER NOT NULL REFERENCES doctors(id),
    patient_name TEXT NOT NULL,
    patient_phone TEXT NOT NULL,
    reason TEXT,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'booked' CHECK (status IN ('booked','cancelled')),
    created_at TEXT NOT NULL,
    cancelled_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_appt_doctor_time ON appointments(doctor_id, start_time, end_time);
"""


class SchedulingError(Exception):
    """Base class for domain errors."""


class ValidationError(SchedulingError):
    pass


class ConflictError(SchedulingError):
    pass


class NotFoundError(SchedulingError):
    pass


class Scheduler:
    """Appointment scheduling with overlap prevention and analytics."""

    def __init__(self, db_path: str = "clinic.db", clock: Callable[[], datetime] = datetime.now) -> None:
        self._clock = clock
        self._conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)

    # ---------------------------------------------------------------- doctors
    def add_doctor(self, name: str, specialty: str) -> dict[str, Any]:
        name, specialty = name.strip(), specialty.strip()
        if not name or not specialty:
            raise ValidationError("Doctor name and specialty are required.")
        try:
            cur = self._conn.execute("INSERT INTO doctors(name, specialty) VALUES (?, ?)", (name, specialty))
        except sqlite3.IntegrityError as exc:
            raise ConflictError(f"Doctor '{name}' already exists.") from exc
        return self.get_doctor(int(cur.lastrowid))

    def get_doctor(self, doctor_id: int) -> dict[str, Any]:
        row = self._conn.execute("SELECT * FROM doctors WHERE id = ?", (doctor_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"Doctor {doctor_id} not found.")
        return dict(row)

    def list_doctors(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._conn.execute("SELECT * FROM doctors ORDER BY name")]

    # ----------------------------------------------------------- validation
    def _validate_slot(self, start: datetime, duration_min: int) -> datetime:
        if duration_min <= 0 or duration_min > MAX_DURATION_MIN or duration_min % SLOT_MINUTES:
            raise ValidationError(
                f"Duration must be a multiple of {SLOT_MINUTES} minutes, up to {MAX_DURATION_MIN}."
            )
        if start.minute % SLOT_MINUTES or start.second or start.microsecond:
            raise ValidationError(f"Start time must be aligned to {SLOT_MINUTES}-minute slots.")
        if start <= self._clock():
            raise ValidationError("Appointments must be in the future.")
        if start.weekday() >= 5:
            raise ValidationError("The clinic is closed on weekends.")
        end = start + timedelta(minutes=duration_min)
        if start.time() < OPEN_TIME or end.time() > CLOSE_TIME or end.date() != start.date():
            raise ValidationError(f"Appointments must fall within {OPEN_TIME:%H:%M}-{CLOSE_TIME:%H:%M}.")
        return end

    # ------------------------------------------------------------- booking
    def book(
        self,
        doctor_id: int,
        patient_name: str,
        patient_phone: str,
        start: datetime,
        duration_min: int = 30,
        reason: Optional[str] = None,
    ) -> dict[str, Any]:
        patient_name = patient_name.strip()
        if len(patient_name) < 2:
            raise ValidationError("Patient name is too short.")
        if not PHONE_RE.match(patient_phone.replace(" ", "")):
            raise ValidationError("Phone must contain 10-13 digits (optional leading +).")
        end = self._validate_slot(start, duration_min)
        self.get_doctor(doctor_id)  # raises NotFoundError

        # BEGIN IMMEDIATE takes the write lock first, so check-then-insert is atomic
        # and two concurrent requests cannot both book the same slot.
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            clash = self._conn.execute(
                """SELECT id FROM appointments
                   WHERE doctor_id = ? AND status = 'booked'
                     AND start_time < ? AND end_time > ?""",
                (doctor_id, end.isoformat(), start.isoformat()),
            ).fetchone()
            if clash:
                raise ConflictError(f"Doctor is already booked in that time range (appointment #{clash['id']}).")
            cur = self._conn.execute(
                """INSERT INTO appointments(doctor_id, patient_name, patient_phone, reason,
                                            start_time, end_time, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (doctor_id, patient_name, patient_phone, reason, start.isoformat(),
                 end.isoformat(), self._clock().isoformat()),
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return self.get_appointment(int(cur.lastrowid))

    def get_appointment(self, appointment_id: int) -> dict[str, Any]:
        row = self._conn.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"Appointment {appointment_id} not found.")
        return dict(row)

    def cancel(self, appointment_id: int) -> dict[str, Any]:
        appt = self.get_appointment(appointment_id)
        if appt["status"] == "cancelled":
            raise ConflictError("Appointment is already cancelled.")
        if datetime.fromisoformat(appt["start_time"]) <= self._clock():
            raise ValidationError("Past appointments cannot be cancelled.")
        self._conn.execute(
            "UPDATE appointments SET status='cancelled', cancelled_at=? WHERE id=?",
            (self._clock().isoformat(), appointment_id),
        )
        return self.get_appointment(appointment_id)

    def list_appointments(
        self, day: Optional[date] = None, doctor_id: Optional[int] = None, status: Optional[str] = None
    ) -> list[dict[str, Any]]:
        query, params = "SELECT * FROM appointments WHERE 1=1", []
        if day:
            query += " AND date(start_time) = ?"
            params.append(day.isoformat())
        if doctor_id is not None:
            query += " AND doctor_id = ?"
            params.append(doctor_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        return [dict(r) for r in self._conn.execute(query + " ORDER BY start_time", params)]

    # ------------------------------------------------------- availability
    def available_slots(self, doctor_id: int, day: date, duration_min: int = 30) -> list[str]:
        """Return start times (HH:MM) where a `duration_min` appointment would fit."""
        self.get_doctor(doctor_id)
        if day.weekday() >= 5:
            return []
        booked = [
            (datetime.fromisoformat(a["start_time"]), datetime.fromisoformat(a["end_time"]))
            for a in self.list_appointments(day, doctor_id, "booked")
        ]
        slots: list[str] = []
        cursor = datetime.combine(day, OPEN_TIME)
        close = datetime.combine(day, CLOSE_TIME)
        step = timedelta(minutes=SLOT_MINUTES)
        while cursor + timedelta(minutes=duration_min) <= close:
            end = cursor + timedelta(minutes=duration_min)
            in_future = cursor > self._clock()
            if in_future and all(not (cursor < b_end and end > b_start) for b_start, b_end in booked):
                slots.append(cursor.strftime("%H:%M"))
            cursor += step
        return slots

    # ---------------------------------------------------------- analytics
    def stats(self) -> dict[str, Any]:
        rows = [dict(r) for r in self._conn.execute(
            "SELECT a.*, d.name AS doctor_name FROM appointments a JOIN doctors d ON d.id = a.doctor_id")]
        total = len(rows)
        cancelled = [r for r in rows if r["status"] == "cancelled"]
        booked = [r for r in rows if r["status"] == "booked"]
        hours = Counter(datetime.fromisoformat(r["start_time"]).hour for r in booked)
        per_doctor = Counter(r["doctor_name"] for r in booked)
        return {
            "total_appointments": total,
            "booked": len(booked),
            "cancelled": len(cancelled),
            "cancellation_rate_pct": round(100 * len(cancelled) / total, 1) if total else 0.0,
            "busiest_hour": f"{hours.most_common(1)[0][0]:02d}:00" if hours else None,
            "appointments_per_doctor": dict(per_doctor),
        }

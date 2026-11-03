from datetime import date, datetime

import pytest

from app.services import ConflictError, NotFoundError, ValidationError

TUE_10 = datetime(2026, 11, 3, 10, 0)
PHONE = "9876543210"


def book(s, start=TUE_10, duration=30, name="Asha Rao"):
    return s.book(1, name, PHONE, start, duration)


def test_successful_booking(scheduler):
    appt = book(scheduler)
    assert appt["status"] == "booked"
    assert appt["end_time"] == "2026-11-03T10:30:00"


def test_exact_double_booking_rejected(scheduler):
    book(scheduler)
    with pytest.raises(ConflictError):
        book(scheduler, name="Someone Else")


@pytest.mark.parametrize("hour,minute,duration", [(9, 45, 30), (10, 15, 30), (10, 0, 60)])
def test_partial_overlaps_rejected(scheduler, hour, minute, duration):
    book(scheduler)  # 10:00-10:30
    with pytest.raises(ConflictError):
        book(scheduler, datetime(2026, 11, 3, hour, minute), duration, "Other Person")


def test_back_to_back_is_allowed(scheduler):
    book(scheduler)
    assert book(scheduler, datetime(2026, 11, 3, 10, 30), name="Next Patient")["status"] == "booked"


def test_cancel_frees_slot(scheduler):
    appt = book(scheduler)
    scheduler.cancel(appt["id"])
    assert book(scheduler, name="New Patient")["status"] == "booked"


def test_cancel_twice_conflicts(scheduler):
    appt = book(scheduler)
    scheduler.cancel(appt["id"])
    with pytest.raises(ConflictError):
        scheduler.cancel(appt["id"])


@pytest.mark.parametrize("start", [
    datetime(2026, 11, 3, 8, 45),    # before opening
    datetime(2026, 11, 3, 16, 45),   # 30 min runs past closing
    datetime(2026, 11, 7, 10, 0),    # Saturday
    datetime(2026, 11, 3, 10, 10),   # not slot-aligned
    datetime(2026, 11, 2, 7, 0),     # in the past
])
def test_invalid_times_rejected(scheduler, start):
    with pytest.raises(ValidationError):
        book(scheduler, start)


@pytest.mark.parametrize("phone", ["123", "abcdefghij", ""])
def test_bad_phone_rejected(scheduler, phone):
    with pytest.raises(ValidationError):
        scheduler.book(1, "Asha Rao", phone, TUE_10)


def test_unknown_doctor(scheduler):
    with pytest.raises(NotFoundError):
        scheduler.book(99, "Asha Rao", PHONE, TUE_10)


def test_available_slots_exclude_booked(scheduler):
    book(scheduler)
    slots = scheduler.available_slots(1, date(2026, 11, 3), 30)
    assert "10:00" not in slots and "10:15" not in slots
    assert "09:30" in slots and "10:30" in slots
    assert slots[-1] == "16:30"


def test_no_slots_on_weekend(scheduler):
    assert scheduler.available_slots(1, date(2026, 11, 7)) == []


def test_stats(scheduler):
    a = book(scheduler)
    book(scheduler, datetime(2026, 11, 3, 11, 0), name="Second Pt")
    scheduler.cancel(a["id"])
    st = scheduler.stats()
    assert st["cancellation_rate_pct"] == 50.0
    assert st["busiest_hour"] == "11:00"

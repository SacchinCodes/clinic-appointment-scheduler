"""Populate the database with realistic demo data: python seed.py"""
import os
import random
from datetime import datetime, timedelta

from app.services import ConflictError, Scheduler, SchedulingError

random.seed(7)
NAMES = ["Arun Kumar", "Priya Nair", "Karthik Raja", "Divya Menon", "Suresh Babu", "Lakshmi Iyer",
         "Mohammed Farook", "Anitha Selvam", "Ravi Shankar", "Meena Krishnan"]
REASONS = ["Fever", "Routine check-up", "Follow-up", "Skin allergy", "Back pain", "Vaccination"]

s = Scheduler(os.getenv("CLINIC_DB", "clinic.db"))
docs = [s.add_doctor(n, sp)["id"] for n, sp in
        [("Dr. Anand Rao", "General Physician"), ("Dr. Sneha Pillai", "Dermatology"),
         ("Dr. Vikram Singh", "Orthopedics")]] if not s.list_doctors() else [d["id"] for d in s.list_doctors()]

day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
created = cancelled = 0
for _ in range(14):
    day += timedelta(days=1)
    for _ in range(25):
        start = day.replace(hour=random.randint(9, 16), minute=random.choice([0, 15, 30, 45]))
        try:
            appt = s.book(random.choice(docs), random.choice(NAMES), f"98{random.randint(10**7, 10**8 - 1)}",
                          start, random.choice([15, 30, 30, 45]), random.choice(REASONS))
            created += 1
            if random.random() < 0.15:
                s.cancel(appt["id"]); cancelled += 1
        except SchedulingError:
            pass  # clashes / out-of-hours attempts are expected in random data
print(f"Seeded {created} appointments ({cancelled} cancelled) across {len(docs)} doctors.")

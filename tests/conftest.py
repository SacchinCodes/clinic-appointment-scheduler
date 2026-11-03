from datetime import datetime

import pytest

from app.services import Scheduler

FIXED_NOW = datetime(2026, 11, 2, 8, 0)  # a Monday


@pytest.fixture
def scheduler(tmp_path):
    s = Scheduler(str(tmp_path / "test.db"), clock=lambda: FIXED_NOW)
    s.add_doctor("Dr. Test", "General")
    return s

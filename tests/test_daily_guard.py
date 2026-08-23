import unittest
from datetime import datetime, timezone

from utils.daily_guard import has_successful_run_today


class DailyGuardTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 23, 1, 0, tzinfo=timezone.utc)

    def test_detects_successful_run_on_same_beijing_day(self):
        runs = [{"id": 1, "conclusion": "success", "created_at": "2026-08-23T00:30:00Z"}]
        self.assertTrue(has_successful_run_today(runs, "2", self.now))

    def test_ignores_current_run_and_previous_days(self):
        runs = [
            {"id": 2, "conclusion": "success", "created_at": "2026-08-23T00:30:00Z"},
            {"id": 1, "conclusion": "success", "created_at": "2026-08-21T16:30:00Z"},
        ]
        self.assertFalse(has_successful_run_today(runs, "2", self.now))


if __name__ == "__main__":
    unittest.main()

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.run_state import load_state, merge_summary, save_state


class RunStateTests(unittest.TestCase):
    def test_state_is_reset_on_a_new_beijing_day(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps({"date": "2026-08-24", "targets": {"x": {}}}))
            with patch.dict(os.environ, {"STATE_FILE": str(path)}):
                state = load_state()
            self.assertNotEqual(state["date"], "2026-08-24")
            self.assertEqual(state["targets"], {})

    def test_summary_round_trip_preserves_target_status(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            summary = {
                "successful": True,
                "targets": [
                    {
                        "account_id": "account-id",
                        "account": "account",
                        "target": "friend",
                        "status": "已确认发送",
                        "attempts": 1,
                    }
                ],
            }
            with patch.dict(os.environ, {"STATE_FILE": str(path)}):
                save_state(merge_summary(load_state(), summary))
                state = load_state()
            self.assertEqual(state["targets"]["account-id:friend"]["status"], "已确认发送")


if __name__ == "__main__":
    unittest.main()

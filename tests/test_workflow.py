import unittest
from pathlib import Path


class WorkflowTests(unittest.TestCase):
    def test_github_workflows_have_no_daily_schedule(self):
        workflow_dir = Path(__file__).parents[1] / ".github" / "workflows"
        scheduled = []
        for workflow in workflow_dir.glob("*.yml"):
            if "schedule:" in workflow.read_text(encoding="utf-8"):
                scheduled.append(workflow.name)
        self.assertEqual(scheduled, [])

    def test_primary_workflow_is_manual_only(self):
        workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "schedule.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("ref: dev", workflow)
        self.assertIn("concurrency:", workflow)

    def test_vps_timer_runs_at_eight_with_half_hour_compensation_windows(self):
        timer = (Path(__file__).parents[1] / "deploy" / "systemd" / "douyin-spark-flow.timer").read_text(
            encoding="utf-8"
        )
        self.assertIn("08:00:00 Asia/Shanghai", timer)
        self.assertIn("08:30:00 Asia/Shanghai", timer)
        self.assertIn("09:00:00 Asia/Shanghai", timer)
        self.assertIn("09:30:00 Asia/Shanghai", timer)
        self.assertNotIn("10:00:00 Asia/Shanghai", timer)


if __name__ == "__main__":
    unittest.main()

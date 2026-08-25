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


if __name__ == "__main__":
    unittest.main()

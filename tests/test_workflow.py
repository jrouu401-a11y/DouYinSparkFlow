import unittest
from pathlib import Path


class WorkflowTests(unittest.TestCase):
    def test_only_primary_workflow_has_a_daily_schedule(self):
        workflow_dir = Path(__file__).parents[1] / ".github" / "workflows"
        scheduled = []
        for workflow in workflow_dir.glob("*.yml"):
            if "schedule:" in workflow.read_text(encoding="utf-8"):
                scheduled.append(workflow.name)
        # A manual-only workflow is intentional while delivery is being verified.
        self.assertTrue(set(scheduled).issubset({"schedule.yml"}), scheduled)

    def test_primary_workflow_uses_main_without_branch_override(self):
        workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "schedule.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("workflow_dispatch:", workflow)
        if "schedule:" in workflow:
            self.assertIn('cron: "0 0 * * *"', workflow)
        self.assertNotIn("ref: dev", workflow)
        self.assertIn("concurrency:", workflow)



if __name__ == "__main__":
    unittest.main()

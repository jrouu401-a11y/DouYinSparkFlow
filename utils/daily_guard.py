import json
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BEIJING_TZ = timezone(timedelta(hours=8))


def has_successful_run_today(runs, current_run_id, now, successful_run_ids=None):
    """Return whether a real delivery run succeeded today.

    ``workflow_run.conclusion == success`` is not enough because a run whose
    delivery step was skipped can still be green.  When ``successful_run_ids``
    is supplied, only run IDs whose delivery step actually succeeded count.
    """
    today = now.astimezone(BEIJING_TZ).date()
    for run in runs:
        if str(run.get("id")) == str(current_run_id):
            continue
        if run.get("conclusion") != "success":
            continue
        if successful_run_ids is not None and str(run.get("id")) not in successful_run_ids:
            continue
        created_at = run.get("created_at")
        if not created_at:
            continue
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if created.astimezone(BEIJING_TZ).date() == today:
            return True
    return False


def write_output(should_run, reason):
    output_path = os.getenv("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as output:
            output.write(f"should_run={'true' if should_run else 'false'}\n")
            output.write(f"reason={reason}\n")
    print(reason)


def main():
    if os.getenv("FORCE_RUN", "false").lower() == "true":
        write_output(True, "Force run requested")
        return

    repository = os.getenv("GITHUB_REPOSITORY")
    token = os.getenv("GITHUB_TOKEN")
    workflow_file = os.getenv("WORKFLOW_FILE", "schedule.yml")
    current_run_id = os.getenv("GITHUB_RUN_ID")
    if not repository or not token or not current_run_id:
        write_output(True, "Local execution; daily guard skipped")
        return

    request = Request(
        f"https://api.github.com/repos/{repository}/actions/workflows/{workflow_file}/runs?per_page=100",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=15) as response:
            runs = json.load(response).get("workflow_runs", [])
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"Unable to check previous workflow runs: {exc}", file=sys.stderr)
        raise SystemExit(1)

    candidate_runs = [
        run
        for run in runs
        if str(run.get("id")) != str(current_run_id)
        and run.get("conclusion") == "success"
    ]
    successful_run_ids = set()
    for run in candidate_runs:
        run_id = run.get("id")
        if not run_id:
            continue
        jobs_request = Request(
            f"https://api.github.com/repos/{repository}/actions/runs/{run_id}/jobs?per_page=100",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen(jobs_request, timeout=15) as response:
                jobs = json.load(response).get("jobs", [])
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"Unable to inspect jobs for workflow run {run_id}: {exc}", file=sys.stderr)
            raise SystemExit(1)
        if any(
            step.get("name") == "Run DouYin Spark Flow"
            and step.get("conclusion") == "success"
            for job in jobs
            for step in (job.get("steps") or [])
        ):
            successful_run_ids.add(str(run_id))

    if has_successful_run_today(
        runs,
        current_run_id,
        datetime.now(tz=timezone.utc),
        successful_run_ids=successful_run_ids,
    ):
        write_output(False, "A successful run already exists for today in Asia/Shanghai")
    else:
        write_output(True, "No successful run exists for today")


if __name__ == "__main__":
    main()

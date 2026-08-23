import json
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BEIJING_TZ = timezone(timedelta(hours=8))


def has_successful_run_today(runs, current_run_id, now):
    today = now.astimezone(BEIJING_TZ).date()
    for run in runs:
        if str(run.get("id")) == str(current_run_id):
            continue
        if run.get("conclusion") != "success":
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

    if has_successful_run_today(runs, current_run_id, datetime.now(tz=timezone.utc)):
        write_output(False, "A successful run already exists for today in Asia/Shanghai")
    else:
        write_output(True, "No successful run exists for today")


if __name__ == "__main__":
    main()

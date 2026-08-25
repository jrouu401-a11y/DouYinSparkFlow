import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


BEIJING_TZ = timezone(timedelta(hours=8))
DEFAULT_STATE_FILE = "data/run-state.json"


def state_path():
    return Path(os.getenv("STATE_FILE", DEFAULT_STATE_FILE))


def today_key(now=None):
    current = now or datetime.now(timezone.utc)
    return current.astimezone(BEIJING_TZ).date().isoformat()


def target_key(account_id, target):
    return f"{account_id}:{target}"


def empty_state(now=None):
    return {"date": today_key(now), "targets": {}}


def load_state(now=None):
    path = state_path()
    if not path.exists():
        return empty_state(now)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_state(now)
    if state.get("date") != today_key(now) or not isinstance(state.get("targets"), dict):
        return empty_state(now)
    return state


def save_state(state):
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="run-state-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(state, output, ensure_ascii=False, indent=2)
            output.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def merge_summary(state, summary):
    for result in summary.get("targets", []):
        account_id = result.get("account_id", result["account"])
        key = target_key(account_id, result["target"])
        state["targets"][key] = {
            "account_id": account_id,
            "account": result["account"],
            "target": result["target"],
            "status": result["status"],
            "attempts": result.get("attempts", 0),
            "matched_name": result.get("matched_name"),
            "reason": result.get("reason"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    state["successful"] = bool(summary.get("successful"))
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    return state

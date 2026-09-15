"""Read-only cloud session probe: never opens an editor or submits a message."""
import json
import os
from pathlib import Path

from core.browser import get_browser
from core.tasks import wait_for_chat_ready
from utils.config import get_config, get_userData


def decoding_comparison(raw):
    result = {"raw_json_valid": False, "legacy_json_valid": False, "legacy_changes_values": None}
    try:
        original = json.loads(raw)
        result["raw_json_valid"] = True
    except ValueError:
        return result
    try:
        legacy = json.loads(raw.encode("utf-8").decode("unicode_escape"))
        result["legacy_json_valid"] = True
        result["legacy_changes_values"] = original != legacy
    except (ValueError, UnicodeError):
        pass
    return result


def probe(context, timeout, records):
    page = context.new_page()
    for stage in ("initial", "reload", "new_tab"):
        record = {"stage": stage, "ready": False}
        records.append(record)
        try:
            if stage == "reload":
                page.reload(wait_until="domcontentloaded", timeout=timeout)
            else:
                if stage == "new_tab":
                    page = context.new_page()
                page.goto("https://www.douyin.com/chat", wait_until="domcontentloaded", timeout=timeout)
            wait_for_chat_ready(page, timeout)
            record["ready"] = True
        except Exception as exc:
            # The readiness helper produces sanitized UI indicators separately.
            record["error_type"] = type(exc).__name__
            return False
    return True


def main():
    playwright = browser = None
    report = {"mode": "diagnostic_only", "successful": False, "accounts": []}
    try:
        report["cookie_decoding"] = decoding_comparison(os.getenv("COOKIES_1230205904", ""))
        config = get_config()
        users = get_userData()
        playwright, browser = get_browser()
        for index, user in enumerate(users):
            record = {"account_index": index, "stages": [], "ready": False}
            report["accounts"].append(record)
            context = browser.new_context()
            try:
                context.set_default_timeout(45000)
                context.add_cookies(user["cookies"])
                record["ready"] = probe(context, 45000, record["stages"])
            finally:
                context.close()
        report["successful"] = bool(report["accounts"]) and all(x["ready"] for x in report["accounts"])
    except Exception as exc:
        report["error_type"] = type(exc).__name__
    finally:
        Path("logs").mkdir(exist_ok=True)
        payload = json.dumps(report, indent=2)
        Path("logs/session-probe.json").write_text(payload, encoding="utf-8")
        if os.getenv("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as output:
                output.write("## Session probe — no messages sent\n```json\n" + payload + "\n```\n")
        if browser:
            browser.close()
        if playwright:
            playwright.stop()
    return 0 if report["successful"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

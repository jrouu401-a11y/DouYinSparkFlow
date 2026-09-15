"""Read-only cloud session probe: never opens an editor or submits a message."""
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from core.browser import get_browser
from core.tasks import wait_for_chat_ready
from utils.config import get_config, get_userData


def session_present(cookies):
    return any(c.get("name") == "sessionid" and bool(c.get("value")) for c in cookies)


def observe_response(response, evidence):
    url = urlsplit(response.url)
    if url.hostname not in {"www.douyin.com", "sso.douyin.com", "passport.douyin.com"}:
        return
    if "/passport/" in url.path:
        kind = "passport"
    elif "/user/self" in url.path:
        kind = "user_self"
    elif "/im/user/" in url.path:
        kind = "im_user"
    else:
        return
    if len(evidence) >= 20:
        return
    item = {"kind": kind, "http_status": response.status}
    try:
        data = response.json()
        if isinstance(data, dict):
            fields = [data]
            if isinstance(data.get("data"), dict):
                fields.append(data["data"])
            for index, obj in enumerate(fields):
                for key in ("status_code", "error_code", "code"):
                    value = obj.get(key)
                    if type(value) is int or (isinstance(value, str) and re.fullmatch(r"-?\d{1,8}", value)):
                        item[str(index) + "_" + key] = value
            messages = " ".join(str(obj.get(key, "")) for obj in fields
                                for key in ("message", "status_msg", "description"))
            item["explicit_login_required"] = bool(re.search(r"未登录|请.*登录|not.?log.?in|login required", messages, re.I))
            item["explicit_session_expired"] = bool(re.search(r"登录.*过期|session.*expired", messages, re.I))
        else:
            item["json_object"] = False
    except Exception:
        item["json_unavailable"] = True
    if item not in evidence:
        evidence.append(item)


def observe_request(request, evidence):
    url = urlsplit(request.url)
    if url.hostname != "www.douyin.com":
        return
    if url.path != "/chat" and not url.path.startswith("/aweme/v1/web/"):
        return
    kind = "chat_document" if url.path == "/chat" else "web_api"
    try:
        header = request.header_value("cookie") or ""
        present = any(part.strip().split("=", 1)[0] == "sessionid" for part in header.split(";"))
        evidence[kind + "_observed"] = True
        evidence[kind + "_session_sent"] = evidence.get(kind + "_session_sent", False) or present
    except Exception:
        evidence[kind + "_inspection_failed"] = True


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
                record["session_in_input"] = session_present(user["cookies"])
                record["session_in_browser_for_chat"] = session_present(context.cookies("https://www.douyin.com/chat"))
                record["transport"] = {}
                record["auth_responses"] = []
                context.on("request", lambda request: observe_request(request, record["transport"]))
                context.on("response", lambda response: observe_response(response, record["auth_responses"]))
                record["ready"] = probe(context, 45000, record["stages"])
                record["session_remaining_for_chat"] = session_present(context.cookies("https://www.douyin.com/chat"))
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

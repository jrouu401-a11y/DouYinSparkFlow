import json
import os
import time
from datetime import datetime, timezone

from playwright.sync_api import Response

from core.browser import get_browser
from core.msg_builder import build_message
from utils import norm
from utils.config import get_config, get_userData
from utils.logger import setup_logger


STATUS_PENDING = "待处理"
STATUS_MATCHED = "已匹配"
STATUS_TYPED = "已输入"
STATUS_SENT = "已确认发送"
STATUS_NOT_FOUND = "未找到"
STATUS_FAILED = "失败"
STATUS_UNCONFIRMED = "未确认"

TERMINAL_STATUSES = {STATUS_SENT, STATUS_NOT_FOUND, STATUS_FAILED, STATUS_UNCONFIRMED}
CONVERSATION_ITEM_SELECTOR = ".conversationConversationItemwrapper"
CONVERSATION_TITLE_SELECTOR = ".conversationConversationItemtitle"
CONVERSATION_LIST_SELECTOR = ".conversationConversationListwrapper"
CHAT_EDITOR_SELECTOR = ".messageEditorimChatEditorContainer"


class TaskExecutionError(RuntimeError):
    pass


def get_logger(config):
    return setup_logger(level=config.get("logLevel", "Info"))


def handle_response(response: Response, user_id_map, logger):
    if "aweme/v1/web/im/user/info" not in response.url:
        return

    try:
        for item in response.json().get("data", []):
            nickname = norm(item.get("nickname"))
            remark_name = norm(item.get("remark_name", nickname))
            user_id_map[remark_name] = [
                item.get("short_id"),
                item.get("unique_id"),
                item.get("sec_uid", ""),
                nickname,
                remark_name,
            ]
    except Exception as exc:
        # The page may close while the final response callback is still queued.
        logger.debug("忽略无法读取的好友信息响应: %s", exc)


def retry_operation(name, operation, retries, logger, delay=2):
    for attempt in range(1, retries + 1):
        try:
            return operation()
        except Exception as exc:
            if attempt == retries:
                raise
            logger.warning("%s 失败，第 %s/%s 次重试: %s", name, attempt, retries, exc)
            time.sleep(delay)


def retry_before_send(operation, retries, logger):
    for attempt in range(1, retries + 1):
        try:
            return operation(), attempt
        except Exception as exc:
            if attempt == retries:
                raise
            logger.warning("发送前准备失败，第 %s/%s 次重试: %s", attempt, retries, exc)
            time.sleep(2)


def create_results(user):
    return {
        target: {
            "account": user["username"],
            "target": target,
            "status": STATUS_PENDING,
            "attempts": 0,
            "matched_name": None,
            "reason": None,
        }
        for target in user["targets"]
    }


def update_result(result, status, reason=None, matched_name=None, attempts=None):
    result["status"] = status
    if reason:
        result["reason"] = str(reason).splitlines()[0][:300]
    if matched_name:
        result["matched_name"] = matched_name
    if attempts is not None:
        result["attempts"] = attempts


def match_target(display_name, targets, user_id_map):
    display_name = norm(display_name)
    values = user_id_map.get(display_name, [])
    return next((value for value in values if value and value in targets), None)


def scroll_and_select_user(page, username, targets, user_id_map, logger):
    remaining_targets = set(targets)
    seen_names = set()
    empty_scrolls = 0

    while remaining_targets:
        elements = page.locator(CONVERSATION_ITEM_SELECTOR).all()
        found_new_name = False

        for element in elements:
            try:
                display_name = norm(element.locator(CONVERSATION_TITLE_SELECTOR).inner_text())
            except Exception as exc:
                logger.debug("读取好友名称失败: %s", exc)
                continue

            if display_name in seen_names:
                continue
            seen_names.add(display_name)
            found_new_name = True

            target = match_target(display_name, remaining_targets, user_id_map)
            if target:
                yield target, display_name, element
                remaining_targets.remove(target)
                break
        else:
            empty_scrolls = 0 if found_new_name else empty_scrolls + 1
            if empty_scrolls >= 10:
                logger.warning("账号 %s 已到好友列表底部", username)
                return

            scrollable = page.locator(CONVERSATION_LIST_SELECTOR).element_handle()
            if not scrollable:
                raise TaskExecutionError(f"账号 {username} 未找到好友列表滚动容器")

            before = page.evaluate("element => element.scrollTop", scrollable)
            page.evaluate("element => element.scrollTop += 800", scrollable)
            time.sleep(1.5)
            after = page.evaluate("element => element.scrollTop", scrollable)
            if before == after:
                empty_scrolls += 2


def clear_editor(editor):
    editor.click()
    editor.press("Control+A")
    editor.press("Backspace")


def type_message(editor, message):
    lines = message.splitlines() or [message]
    for index, line in enumerate(lines):
        editor.type(line)
        if index < len(lines) - 1:
            editor.press("Shift+Enter")


def editor_is_empty(editor):
    try:
        return not norm(editor.inner_text())
    except Exception:
        return False


def confirm_message_sent(editor, timeout_seconds=3):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if editor_is_empty(editor):
            return True
        time.sleep(0.25)
    return editor_is_empty(editor)


def prepare_message(element, page, message, timeout):
    element.click()
    editor = page.locator(CHAT_EDITOR_SELECTOR)
    editor.wait_for(state="visible", timeout=timeout)
    clear_editor(editor)
    type_message(editor, message)
    return editor


def mark_unfinished(results, status, reason):
    for result in results.values():
        if result["status"] not in TERMINAL_STATUSES:
            update_result(result, status, reason=reason)


def run_user_task(browser, user, results, config, logger):
    context = None
    try:
        context = browser.new_context()
        context.set_default_navigation_timeout(config["browserTimeout"])
        context.set_default_timeout(config["browserTimeout"])
        context.add_cookies(user["cookies"])

        page = context.new_page()
        user_id_map = {}
        page.on("response", lambda response: handle_response(response, user_id_map, logger))

        retry_operation(
            "打开抖音聊天页面",
            lambda: page.goto("https://www.douyin.com/chat"),
            config["taskRetryTimes"],
            logger,
            delay=5,
        )
        time.sleep(5)

        for target, display_name, element in scroll_and_select_user(
            page, user["username"], user["targets"], user_id_map, logger
        ):
            result = results[target]
            update_result(result, STATUS_MATCHED, matched_name=display_name)
            message = build_message()

            try:
                editor, attempts = retry_before_send(
                    lambda: prepare_message(element, page, message, config["browserTimeout"]),
                    config["taskRetryTimes"],
                    logger,
                )
                update_result(result, STATUS_TYPED, attempts=attempts)
                editor.press("Enter")

                if confirm_message_sent(editor):
                    update_result(result, STATUS_SENT)
                    logger.info("账号 %s 已确认发送给 %s", user["username"], target)
                else:
                    update_result(result, STATUS_UNCONFIRMED, "发送后未确认输入框清空")
            except Exception as exc:
                update_result(result, STATUS_FAILED, exc)

        for result in results.values():
            if result["status"] == STATUS_PENDING:
                update_result(result, STATUS_NOT_FOUND, "好友列表中未找到匹配目标")
    except Exception as exc:
        mark_unfinished(results, STATUS_FAILED, exc)
    finally:
        if context:
            try:
                context.close()
            except Exception as exc:
                logger.debug("关闭浏览器上下文失败: %s", exc)


def build_summary(results):
    targets = [result for account_results in results.values() for result in account_results.values()]
    confirmed = [result for result in targets if result["status"] == STATUS_SENT]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_count": len(targets),
        "confirmed_count": len(confirmed),
        "successful": len(targets) > 0 and len(confirmed) == len(targets),
        "targets": targets,
    }


def write_summary(summary):
    os.makedirs("logs", exist_ok=True)
    with open("logs/summary.json", "w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)

    lines = [
        "## DouYin Spark Flow Summary",
        "",
        f"- Targets: {summary['target_count']}",
        f"- Confirmed: {summary['confirmed_count']}",
        f"- Result: {'success' if summary['successful'] else 'failure'}",
        "",
        "| Target | Status | Attempts | Matched name | Reason |",
        "| --- | --- | ---: | --- | --- |",
    ]
    if summary.get("configuration_error"):
        lines.insert(5, f"- Configuration error: {summary['configuration_error']}")
    for result in summary["targets"]:
        lines.append(
            "| {target} | {status} | {attempts} | {matched_name} | {reason} |".format(
                target=result["target"],
                status=result["status"],
                attempts=result["attempts"],
                matched_name=result["matched_name"] or "",
                reason=result["reason"] or "",
            )
        )

    markdown = "\n".join(lines) + "\n"
    with open("logs/summary.md", "w", encoding="utf-8") as file:
        file.write(markdown)

    github_summary = os.getenv("GITHUB_STEP_SUMMARY")
    if github_summary:
        with open(github_summary, "a", encoding="utf-8") as file:
            file.write(markdown)


def runTasks():
    try:
        config = get_config()
        users = get_userData()
    except Exception as exc:
        write_summary(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "target_count": 0,
                "confirmed_count": 0,
                "successful": False,
                "targets": [],
                "configuration_error": str(exc).splitlines()[0][:300],
            }
        )
        raise

    logger = get_logger(config)
    all_results = {user["unique_id"]: create_results(user) for user in users}
    playwright = browser = None

    try:
        playwright, browser = get_browser()
        logger.info("开始执行任务")
        for user in users:
            logger.info("开始处理账号 %s", user["username"])
            run_user_task(browser, user, all_results[user["unique_id"]], config, logger)
    except Exception as exc:
        for results in all_results.values():
            mark_unfinished(results, STATUS_FAILED, exc)
    finally:
        if browser:
            browser.close()
        if playwright:
            playwright.stop()

        summary = build_summary(all_results)
        write_summary(summary)

    if not summary["successful"]:
        raise TaskExecutionError(
            f"任务未全部完成: {summary['confirmed_count']}/{summary['target_count']} 个目标已确认发送"
        )

import json
import os
import re
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
CURRENT_CONVERSATION_SELECTOR = (
    ".conversationConversationItemwrapper.conversationConversationItemcurConversation"
)
CHAT_HEADER_TITLE_SELECTOR = ".RightPanelHeadertitle"
# The wrapper is not focusable; keystrokes must be sent to its Slate editor.
CHAT_EDITOR_SELECTOR = '.messageEditorimChatEditorContainer [contenteditable="true"]'
SEND_BUTTON_SELECTOR = '.e2e-send-msg-btn'
OUTBOUND_TEXT_SELECTOR = '.messageMessageBoxisFromMe .MessageItemTextbubbleTextContent'


class TaskExecutionError(RuntimeError):
    pass


def get_logger(config):
    return setup_logger(level=config.get("logLevel", "Info"))


def handle_response(response: Response, user_id_map, logger):
    if "aweme/v1/web/im/user/info" not in response.url:
        return

    try:
        for item in response.json().get("data", []):
            nickname = norm(item.get("nickname") or "")
            remark_name = norm(item.get("remark_name") or nickname)
            identifiers = [
                str(item.get("short_id") or ""),
                str(item.get("unique_id") or ""),
                item.get("sec_uid", ""),
                nickname,
                remark_name,
            ]
            # The conversation list can render either an original nickname or
            # a user-set remark.  Retain the same server-provided identifiers
            # for both labels; matching policy is enforced separately below.
            user_id_map[nickname] = identifiers
            user_id_map[remark_name] = identifiers
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


def match_target(display_name, targets, user_id_map, match_mode):
    display_name = norm(display_name)
    values = user_id_map.get(display_name, [])
    if match_mode == "short_id":
        # Users call both legacy numeric IDs and custom handles their Douyin
        # ID. The API stores the custom handle in unique_id, not short_id.
        candidates = values[1:2] + values[:1]
    elif match_mode == "nickname":
        candidates = values[3:4]
    else:
        raise ValueError(f"Unsupported match mode: {match_mode}")
    return next((value for value in candidates if value and value in targets), None)


def scroll_and_select_user(
    page, username, targets, user_id_map, logger, match_mode, scroll_wait_seconds=1.5
):
    remaining_targets = set(targets)
    empty_scrolls = 0
    rescanned_from_top = False

    while remaining_targets:
        elements = page.locator(CONVERSATION_ITEM_SELECTOR).all()

        for element in elements:
            try:
                display_name = norm(element.locator(CONVERSATION_TITLE_SELECTOR).inner_text())
            except Exception as exc:
                logger.debug("读取好友名称失败: %s", exc)
                continue

            target = match_target(
                display_name, remaining_targets, user_id_map, match_mode
            )
            if target:
                yield target, display_name, element
                remaining_targets.remove(target)
                break
        else:
            scrollable = page.locator(CONVERSATION_LIST_SELECTOR).element_handle()
            if not scrollable:
                raise TaskExecutionError(f"账号 {username} 未找到好友列表滚动容器")

            before = page.evaluate("element => element.scrollTop", scrollable)
            page.evaluate("element => element.scrollTop += 800", scrollable)
            time.sleep(scroll_wait_seconds)
            after = page.evaluate("element => element.scrollTop", scrollable)
            if before != after:
                empty_scrolls = 0
                continue

            empty_scrolls += 1
            if empty_scrolls < 5:
                continue

            # User info arrives asynchronously. Re-scan from the top once so a
            # name first seen before its mapping arrived is not skipped forever.
            if not rescanned_from_top:
                logger.info("账号 %s 重新扫描好友列表以等待好友信息加载", username)
                page.evaluate("element => element.scrollTop = 0", scrollable)
                rescanned_from_top = True
                empty_scrolls = 0
                time.sleep(scroll_wait_seconds)
                continue

            logger.warning("账号 %s 已到好友列表底部", username)
            return


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


def message_echo_count(page, message):
    try:
        return page.locator(OUTBOUND_TEXT_SELECTOR).evaluate_all(
            """(nodes, message) => {
                const text = node => node.nodeType === 3 ? node.textContent :
                    node.nodeName === 'IMG' ? (node.getAttribute('title') || node.getAttribute('alt') || '') :
                    node.nodeName === 'BR' ? '\\n' : Array.from(node.childNodes).map(text).join('');
                return nodes.filter(node => text(node).trim() === message.trim()).length;
            }""", message
        )
    except Exception:
        return 0


def conversation_is_selected(page, display_name):
    """Return whether both chat panes show the conversation just selected."""
    try:
        active_item = page.locator(CURRENT_CONVERSATION_SELECTOR)
        if not active_item.count():
            return False
        active_name = norm(active_item.locator(CONVERSATION_TITLE_SELECTOR).inner_text())
        header_name = norm(page.locator(CHAT_HEADER_TITLE_SELECTOR).inner_text())
        return active_name == norm(display_name) and header_name == norm(display_name)
    except Exception:
        return False


def wait_for_conversation_selection(page, display_name, timeout):
    deadline = time.monotonic() + timeout / 1000
    while time.monotonic() < deadline:
        if conversation_is_selected(page, display_name):
            return
        time.sleep(0.1)
    raise TaskExecutionError(f"会话未切换到好友 {display_name}")


def confirm_message_sent(
    page,
    editor,
    message,
    before_message_count,
    timeout_seconds=5,
    display_name=None,
):
    """Confirm that the current conversation visibly contains the new message.

    A successful response from a generic IM endpoint is not sufficient: it can
    acknowledge a request that did not produce an outbound message in the
    selected conversation.  We never press Enter again here, so an
    inconclusive send remains ``未确认`` rather than being duplicated.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        echoed = message_echo_count(page, message) > before_message_count
        cleared = editor_is_empty(editor)
        if echoed and cleared:
            break
        time.sleep(0.25)
    visible_echo = (
        message_echo_count(page, message) > before_message_count
        and editor_is_empty(editor)
    )
    if not visible_echo or not display_name:
        return False
    # A local optimistic bubble is not proof of delivery. Reload the server
    # history and reopen the exact conversation before declaring success.
    page.reload(wait_until="domcontentloaded")
    page.locator(CONVERSATION_LIST_SELECTOR).wait_for(state="visible")
    items = page.locator(CONVERSATION_ITEM_SELECTOR).filter(
        has=page.locator(CONVERSATION_TITLE_SELECTOR).filter(has_text=re.compile(r"^" + re.escape(display_name) + r"$"))
    )
    if items.count() != 1:
        return False
    items.click()
    wait_for_conversation_selection(page, display_name, 15000)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if message_echo_count(page, message) > before_message_count:
            return True
        time.sleep(0.25)
    return False


def prepare_message(element, page, display_name, message, timeout):
    element.click()
    wait_for_conversation_selection(page, display_name, timeout)
    editor = page.locator(CHAT_EDITOR_SELECTOR)
    editor.wait_for(state="visible", timeout=timeout)
    before_message_count = message_echo_count(page, message)
    clear_editor(editor)
    type_message(editor, message)
    return editor, before_message_count


def select_requested_targets(users, requested):
    if not requested.strip():
        return users
    targets = set(filter(None, re.split(r"[\s,，]+", requested.strip())))
    known = {target for user in users for target in user["targets"]}
    if targets - known:
        raise TaskExecutionError("指定补发目标不在 TASKS 名单中")
    return [dict(user, targets=[target for target in user["targets"] if target in targets])
            for user in users if targets.intersection(user["targets"])]


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
        def on_response(response):
            handle_response(response, user_id_map, logger)

        page.on("response", on_response)

        retry_operation(
            "打开抖音聊天页面",
            lambda: page.goto("https://www.douyin.com/chat", wait_until="domcontentloaded"),
            config["taskRetryTimes"],
            logger,
            delay=5,
        )
        time.sleep(5)

        # An expired/invalid Cookie lands on the login page.  Detect this
        # before querying the chat DOM so every target gets a useful failure
        # reason instead of waiting for the old conversation selector timeout.
        if hasattr(page, "locator"):
            login_marker = page.locator("text=登录")
            conversation_list = page.locator(CONVERSATION_LIST_SELECTOR)
            if login_marker.count() and not conversation_list.count():
                raise TaskExecutionError("Cookie 已失效或未登录，请更新 Cookies Secret")

        for target, display_name, element in scroll_and_select_user(
            page,
            user["username"],
            user["targets"],
            user_id_map,
            logger,
            config["matchMode"],
            scroll_wait_seconds=max(config["friendListTimeout"] / 1000, 0.2),
        ):
            result = results[target]
            update_result(result, STATUS_MATCHED, matched_name=display_name)
            message = build_message()

            submitted = False
            try:
                prepared_message, attempts = retry_before_send(
                    lambda: prepare_message(
                        element, page, display_name, message, config["browserTimeout"]
                    ),
                    config["taskRetryTimes"],
                    logger,
                )
                editor, before_message_count = prepared_message
                update_result(result, STATUS_TYPED, attempts=attempts)
                submitted = True
                page.locator(SEND_BUTTON_SELECTOR).click()

                if confirm_message_sent(
                    page,
                    editor,
                    message,
                    before_message_count,
                    display_name=display_name,
                ):
                    update_result(result, STATUS_SENT)
                    logger.info("账号 %s 已确认发送给 %s", user["username"], target)
                else:
                    update_result(result, STATUS_UNCONFIRMED, "发送后未能确认刷新会话仍有新增消息")
            except Exception as exc:
                update_result(result, STATUS_UNCONFIRMED if submitted else STATUS_FAILED, exc)

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
        users = select_requested_targets(users, os.getenv("ONLY_TARGETS", ""))
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

import os, sys
from enum import Enum
import json
import logging
from utils.logger import setup_logger
from utils import norm

logger = setup_logger(level=logging.DEBUG)

"""
是否启用调试模式
更详细的日志打印，浏览器操作可视化等
"""
DEBUG = True
config = None
userData = None


class ConfigurationError(ValueError):
    pass


class Environment(Enum):
    GITHUBACTION = "GITHUB_ACTION"  # GitHub Action 运行
    LOCAL = "LOCAL"  # 本地代码运行
    PACKED = "PACKED"  # PyInstaller 打包运行

    def __str__(self):
        return self.value


def get_environment():
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Environment.PACKED
    elif os.getenv("GITHUB_ACTIONS") == "true":
        return Environment.GITHUBACTION
    else:
        return Environment.LOCAL


def get_config():
    """
    获取配置信息
    :return: 配置字典
    """
    global config

    if config:
        return config

    match_mode = os.getenv("MATCH_MODE", "nickname")
    if match_mode not in {"nickname", "short_id"}:
        raise ConfigurationError("MATCH_MODE 必须为 nickname 或 short_id")

    config = {
        "proxyAddress": os.getenv("PROXY_ADDRESS", ""),
        "messageTemplate": os.getenv(
            "MESSAGE_TEMPLATE",
            "[盖瑞]今日火花[加一]\\n—— [右边] 每日一言 [左边] ——\\n[API]",
        ),
        "hitokotoTypes": json.loads(
            os.getenv("HITOKOTO_TYPES", '["文学","影视","诗词","哲学"]')
        ),
        "matchMode": match_mode,  # 是否使用短 ID 进行好友匹配
        "browserTimeout": int(
            os.getenv("BROWSER_TIMEOUT", "120000")
        ),  # 浏览器操作超时时间，单位毫秒
        "friendListTimeout": int(
            os.getenv("FRIEND_LIST_WAIT_TIME", "2000")
        ),  # 好友列表加载超时时间，单位毫秒
        "taskRetryTimes": int(os.getenv("TASK_RETRY_TIMES", "3")),  # 任务重试次数
        "logLevel": os.getenv("LOG_LEVEL", "DEBUG"),  # 日志级别
    }

    return config


def sanitize_cookies(cookies):
    for cookie in cookies:
        if "sameSite" in cookie:
            cookie.pop("sameSite")  # 移除 sameSite 字段，Playwright 可能不支持该字段
    return cookies


def get_userData():
    """
    获取用户数据目录
    :return: 用户数据目录路径
    """
    global userData

    if userData:
        return userData

    try:
        tasks = json.loads(os.getenv("TASKS", "[]"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError("TASKS 不是有效 JSON") from exc

    if not isinstance(tasks, list) or not tasks:
        raise ConfigurationError("TASKS 至少需要一个账号任务")

    userData = []

    for task in tasks:
        if not isinstance(task, dict):
            raise ConfigurationError("TASKS 中的每项必须是对象")

        username = task.get("username", "未知用户")
        unique_id = task.get("unique_id")
        if not unique_id:
            raise ConfigurationError(f"{username} 的任务缺少 unique_id")

        targets = task.get("targets")
        if not isinstance(targets, list) or not targets:
            raise ConfigurationError(f"{username} 的任务缺少目标好友")
        normalized_targets = [norm(str(target)) for target in targets if norm(str(target))]
        if len(normalized_targets) != len(targets):
            raise ConfigurationError(f"{username} 的任务存在空目标好友")
        if len(set(normalized_targets)) != len(normalized_targets):
            raise ConfigurationError(f"{username} 的任务存在重复目标好友")
        cookies_key = f"cookies_{unique_id}".upper()
        cookies_str = (
            os.getenv(cookies_key, "").encode("utf-8").decode("unicode_escape")
        )
        if not cookies_str:
            raise ConfigurationError(f"{username} 的任务缺少 {cookies_key} 环境变量")
        try:
            cookies = json.loads(cookies_str)
        except json.JSONDecodeError as exc:
            raise ConfigurationError(f"{username} 的任务 {cookies_key} 格式不正确") from exc

        if not isinstance(cookies, list) or not cookies:
            raise ConfigurationError(f"{username} 的任务 {cookies_key} 不能为空")

        userData.append(
            {
                "unique_id": unique_id,
                "username": username,
                "cookies": sanitize_cookies(cookies),
                "targets": normalized_targets,
            }
        )

    return userData

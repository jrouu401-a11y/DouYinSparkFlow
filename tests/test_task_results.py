import unittest
from unittest.mock import patch

import core.tasks as tasks


class FakeContext:
    def set_default_navigation_timeout(self, timeout):
        pass

    def set_default_timeout(self, timeout):
        pass

    def add_cookies(self, cookies):
        pass

    def new_page(self):
        return FakePage()

    def close(self):
        pass


class FakeBrowser:
    def new_context(self):
        return FakeContext()


class FakePage:
    def on(self, event, callback):
        pass

    def goto(self, url):
        return None


class FakeEditor:
    def __init__(self):
        self.presses = []

    def press(self, key):
        self.presses.append(key)


class DelayedMappingTitle:
    def inner_text(self):
        return "Friend"


class DelayedMappingElement:
    def locator(self, selector):
        self.selector = selector
        return DelayedMappingTitle()


class DelayedMappingList:
    def __init__(self, element):
        self.element = element

    def all(self):
        return [self.element]

    def element_handle(self):
        return object()


class DelayedMappingPage:
    def __init__(self, user_id_map):
        self.user_id_map = user_id_map
        self.scroll_top = 0
        self.element = DelayedMappingElement()

    def locator(self, selector):
        if selector == tasks.CONVERSATION_ITEM_SELECTOR:
            return DelayedMappingList(self.element)
        if selector == tasks.CONVERSATION_LIST_SELECTOR:
            return DelayedMappingList(self.element)
        raise AssertionError(f"Unexpected selector: {selector}")

    def evaluate(self, script, scrollable):
        if "+= 800" in script:
            self.scroll_top = 800
            self.user_id_map["Friend"] = ["friend", "", "", "Friend", "Friend"]
            return None
        return self.scroll_top


class TaskResultTests(unittest.TestCase):
    def setUp(self):
        self.user = {
            "username": "account",
            "unique_id": "123",
            "cookies": [{"name": "sessionid"}],
            "targets": ["friend"],
        }
        self.config = {
            "browserTimeout": 1,
            "friendListTimeout": 2000,
            "taskRetryTimes": 3,
        }

    def test_unconfirmed_send_is_not_retried_after_enter(self):
        results = tasks.create_results(self.user)
        editor = FakeEditor()
        logger = tasks.get_logger({"logLevel": "Error"})
        element = object()

        with patch.object(tasks.time, "sleep"), patch.object(
            tasks, "scroll_and_select_user", return_value=iter([("friend", "Friend", element)])
        ), patch.object(
            tasks, "build_message", return_value="message"
        ), patch.object(
            tasks, "retry_before_send", return_value=(editor, 1)
        ), patch.object(tasks, "confirm_message_sent", return_value=False):
            tasks.run_user_task(FakeBrowser(), self.user, results, self.config, logger)

        self.assertEqual(editor.presses, ["Enter"])
        self.assertEqual(results["friend"]["status"], tasks.STATUS_UNCONFIRMED)

    def test_incomplete_summary_is_not_successful(self):
        results = {"123": tasks.create_results(self.user)}
        summary = tasks.build_summary(results)
        self.assertFalse(summary["successful"])
        self.assertEqual(summary["confirmed_count"], 0)

    def test_match_target_uses_short_id_from_response(self):
        user_id_map = {"Friend": ["friend", "other", "", "Friend", "Friend"]}
        self.assertEqual(tasks.match_target("Friend", {"friend"}, user_id_map), "friend")

    def test_scroll_rechecks_name_after_delayed_user_mapping_arrives(self):
        user_id_map = {}
        page = DelayedMappingPage(user_id_map)
        logger = tasks.get_logger({"logLevel": "Error"})

        with patch.object(tasks.time, "sleep"):
            matched_target, display_name, _ = next(
                tasks.scroll_and_select_user(
                    page, "account", ["friend"], user_id_map, logger
                )
            )

        self.assertEqual(matched_target, "friend")
        self.assertEqual(display_name, "Friend")


if __name__ == "__main__":
    unittest.main()

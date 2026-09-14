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
    clicks = 0

    def locator(self, selector):
        return self

    def count(self):
        return 0

    def click(self):
        FakePage.clicks += 1

    def on(self, event, callback):
        pass

    def goto(self, url, **kwargs):
        return None


class FakeEditor:
    def __init__(self):
        self.presses = []

    def press(self, key):
        self.presses.append(key)


class FakeTextLocator:
    def __init__(self, count):
        self._count = count

    def count(self):
        return self._count

    def evaluate_all(self, script, message):
        return self._count


class FakeMessagePage:
    def __init__(self, message_count):
        self.message_count = message_count

    def get_by_text(self, message, exact):
        self.message = message
        self.exact = exact
        return FakeTextLocator(self.message_count)

    def locator(self, selector):
        assert selector == tasks.OUTBOUND_TEXT_SELECTOR
        return FakeTextLocator(self.message_count)


class EmptyEditor:
    def inner_text(self):
        return ""


class FilledEditor:
    def inner_text(self):
        return "message"


class StaticTextLocator:
    def __init__(self, text, count=1):
        self.text = text
        self._count = count

    def count(self):
        return self._count

    def inner_text(self):
        return self.text


class CurrentConversationLocator(StaticTextLocator):
    def locator(self, selector):
        if selector != tasks.CONVERSATION_TITLE_SELECTOR:
            raise AssertionError(f"Unexpected selector: {selector}")
        return StaticTextLocator(self.text)


class ConversationSelectionPage:
    def __init__(self, active_name, header_name, active=True):
        self.active_name = active_name
        self.header_name = header_name
        self.active = active

    def locator(self, selector):
        if selector == tasks.CURRENT_CONVERSATION_SELECTOR:
            return CurrentConversationLocator(self.active_name, int(self.active))
        if selector == tasks.CHAT_HEADER_TITLE_SELECTOR:
            return StaticTextLocator(self.header_name)
        raise AssertionError(f"Unexpected selector: {selector}")


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
            "matchMode": "short_id",
        }

    def test_unconfirmed_send_is_not_retried_after_enter(self):
        FakePage.clicks = 0
        results = tasks.create_results(self.user)
        editor = FakeEditor()
        logger = tasks.get_logger({"logLevel": "Error"})
        element = object()

        with patch.object(tasks.time, "sleep"), patch.object(
            tasks, "scroll_and_select_user", return_value=iter([("friend", "Friend", element)])
        ), patch.object(
            tasks, "build_message", return_value="message"
        ), patch.object(
            tasks, "retry_before_send", return_value=((editor, 0), 1)
        ), patch.object(tasks, "confirm_message_sent", return_value=False):
            tasks.run_user_task(FakeBrowser(), self.user, results, self.config, logger)

        self.assertEqual(editor.presses, [])
        self.assertEqual(FakePage.clicks, 1)
        self.assertEqual(results["friend"]["status"], tasks.STATUS_UNCONFIRMED)

    def test_confirmation_requires_message_to_survive_reload(self):
        from unittest.mock import MagicMock
        for persisted, expected in [(False, False), (True, True)]:
            page = MagicMock()
            page.locator.return_value.filter.return_value.count.return_value = 1
            def count_message(page, message):
                return int(not page.reload.called or persisted)
            with patch.object(tasks, "message_echo_count", side_effect=count_message), patch.object(
                tasks, "wait_for_conversation_selection"
            ), patch.object(tasks.time, "monotonic", side_effect=range(100)), patch.object(tasks.time, "sleep"):
                confirmed = tasks.confirm_message_sent(
                    page, EmptyEditor(), "message", 0, timeout_seconds=0, display_name="Friend"
                )
            self.assertEqual(confirmed, expected)
            page.reload.assert_called_once_with(wait_until="domcontentloaded")

    def test_incomplete_summary_is_not_successful(self):
        results = {"123": tasks.create_results(self.user)}
        summary = tasks.build_summary(results)
        self.assertFalse(summary["successful"])
        self.assertEqual(summary["confirmed_count"], 0)

    def test_id_mode_matches_custom_handle_and_numeric_id_but_not_nickname(self):
        user_id_map = {"Friend": ["friend", "other", "", "Friend", "Friend"]}
        self.assertEqual(
            tasks.match_target("Friend", {"friend"}, user_id_map, "short_id"),
            "friend",
        )
        self.assertIsNone(
            tasks.match_target("Friend", {"Friend"}, user_id_map, "short_id")
        )
        self.assertEqual(tasks.match_target("Friend", {"other"}, user_id_map, "short_id"), "other")

    def test_target_subset_cannot_add_unconfigured_recipient(self):
        with self.assertRaises(tasks.TaskExecutionError):
            tasks.select_requested_targets([self.user], "unknown")
        selected = tasks.select_requested_targets([self.user], "friend")
        self.assertEqual(selected[0]["targets"], ["friend"])

    def test_nickname_mode_uses_only_original_nickname_from_response(self):
        user_id_map = {"Remark": ["friend", "other", "", "Friend", "Remark"]}
        self.assertEqual(
            tasks.match_target("Remark", {"Friend"}, user_id_map, "nickname"),
            "Friend",
        )
        self.assertIsNone(
            tasks.match_target("Remark", {"friend"}, user_id_map, "nickname")
        )

    def test_cleared_editor_without_message_echo_is_not_confirmation(self):
        page = FakeMessagePage(message_count=0)
        editor = FilledEditor()

        self.assertFalse(
            tasks.confirm_message_sent(
                page,
                editor,
                "message",
                before_message_count=0,
                timeout_seconds=0,
            )
        )

    def test_message_echo_after_submit_is_confirmation(self):
        page = FakeMessagePage(message_count=1)
        editor = FilledEditor()

        self.assertFalse(
            tasks.confirm_message_sent(
                page,
                editor,
                "message",
                before_message_count=0,
                timeout_seconds=0,
            )
        )

    def test_empty_editor_without_message_echo_is_not_confirmation(self):
        page = FakeMessagePage(message_count=0)
        editor = EmptyEditor()

        self.assertFalse(
            tasks.confirm_message_sent(
                page,
                editor,
                "message",
                before_message_count=0,
                timeout_seconds=0,
            )
        )

    def test_local_echo_without_reloaded_history_is_not_confirmation(self):
        page = FakeMessagePage(message_count=1)
        editor = EmptyEditor()

        self.assertFalse(
            tasks.confirm_message_sent(
                page,
                editor,
                "message",
                before_message_count=0,
                timeout_seconds=0,
            )
        )

    def test_conversation_selection_requires_matching_active_item_and_header(self):
        self.assertFalse(
            tasks.conversation_is_selected(
                ConversationSelectionPage("Friend", "Previous chat"), "Friend"
            )
        )
        self.assertTrue(
            tasks.conversation_is_selected(
                ConversationSelectionPage("Friend", "Friend"), "Friend"
            )
        )

    def test_scroll_rechecks_name_after_delayed_user_mapping_arrives(self):
        user_id_map = {}
        page = DelayedMappingPage(user_id_map)
        logger = tasks.get_logger({"logLevel": "Error"})

        with patch.object(tasks.time, "sleep"):
            matched_target, display_name, _ = next(
                tasks.scroll_and_select_user(
                    page, "account", ["friend"], user_id_map, logger, "short_id"
                )
            )

        self.assertEqual(matched_target, "friend")
        self.assertEqual(display_name, "Friend")


if __name__ == "__main__":
    unittest.main()

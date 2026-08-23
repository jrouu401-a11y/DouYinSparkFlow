import json
import os
import unittest
from unittest.mock import patch

import utils.config as config_module


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.old_config = config_module.config
        self.old_user_data = config_module.userData
        config_module.config = None
        config_module.userData = None

    def tearDown(self):
        config_module.config = self.old_config
        config_module.userData = self.old_user_data

    def test_missing_cookie_is_a_configuration_error(self):
        tasks = json.dumps(
            [{"username": "account", "unique_id": "123", "targets": ["friend"]}]
        )
        with patch.dict(os.environ, {"TASKS": tasks}, clear=True):
            with self.assertRaises(config_module.ConfigurationError):
                config_module.get_userData()

    def test_empty_targets_are_a_configuration_error(self):
        tasks = json.dumps(
            [{"username": "account", "unique_id": "123", "targets": []}]
        )
        with patch.dict(os.environ, {"TASKS": tasks, "COOKIES_123": "[]"}, clear=True):
            with self.assertRaises(config_module.ConfigurationError):
                config_module.get_userData()

    def test_valid_task_normalizes_targets(self):
        tasks = json.dumps(
            [{"username": "account", "unique_id": "123", "targets": ["  friend  "]}]
        )
        cookies = json.dumps([{"name": "sessionid", "value": "x", "domain": ".douyin.com", "path": "/"}])
        with patch.dict(
            os.environ,
            {"TASKS": tasks, "COOKIES_123": cookies},
            clear=True,
        ):
            self.assertEqual(config_module.get_userData()[0]["targets"], ["friend"])


if __name__ == "__main__":
    unittest.main()

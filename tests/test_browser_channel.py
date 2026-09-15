import unittest
from unittest.mock import patch, MagicMock

from core.browser import get_browser, Environment


class BrowserChannelTests(unittest.TestCase):
    def test_default_sender_and_opt_in_probe_channels(self):
        for channel in (None, 'chromium'):
            runtime = MagicMock()
            with patch('core.browser.get_environment', return_value=Environment.GITHUBACTION), patch(
                'core.browser.sync_playwright', return_value=runtime
            ):
                get_browser(channel=channel)
            options = {'headless': True}
            if channel:
                options['channel'] = channel
            runtime.start.return_value.chromium.launch.assert_called_once_with(**options)

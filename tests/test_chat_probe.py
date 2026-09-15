import unittest
from unittest.mock import MagicMock, patch

from utils.chat_probe import probe, decoding_comparison


class ProbeTests(unittest.TestCase):
    def test_decode_comparison_exposes_only_verdicts(self):
        import json
        result = decoding_comparison(json.dumps([{"value": "ordinary"}]))
        self.assertEqual(result, {"raw_json_valid": True, "legacy_json_valid": True, "legacy_changes_values": False})
        result = decoding_comparison(json.dumps([{"value": 'a"b'}]))
        self.assertTrue(result["raw_json_valid"])
        self.assertFalse(result["legacy_json_valid"])

    def test_reads_initial_reload_and_new_tab_without_sending(self):
        context = MagicMock()
        records = []
        with patch('utils.chat_probe.wait_for_chat_ready') as ready:
            self.assertTrue(probe(context, 45000, records))
        self.assertEqual([r['stage'] for r in records], ['initial', 'reload', 'new_tab'])
        self.assertEqual(ready.call_count, 3)
        self.assertEqual(context.new_page.call_count, 2)
        context.new_page.return_value.locator.assert_not_called()

    def test_reload_failure_is_identified_without_repeating(self):
        context = MagicMock()
        records = []
        with patch('utils.chat_probe.wait_for_chat_ready', side_effect=[None, RuntimeError('private')]):
            self.assertFalse(probe(context, 45000, records))
        self.assertEqual(len(records), 2)
        self.assertEqual(records[-1], {'stage': 'reload', 'ready': False, 'error_type': 'RuntimeError'})
        self.assertEqual(context.new_page.call_count, 1)

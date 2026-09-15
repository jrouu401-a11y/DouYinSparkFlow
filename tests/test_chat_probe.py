import unittest
from unittest.mock import MagicMock, patch

from utils.chat_probe import probe, decoding_comparison, observe_request, observe_response


class ProbeTests(unittest.TestCase):
    def test_auth_response_keeps_codes_and_classification_only(self):
        response = MagicMock()
        response.url = 'https://www.douyin.com/aweme/v1/web/user/self/?secret=x'
        response.status = 200
        response.json.return_value = {'status_code': 8, 'status_msg': '请先登录', 'user': {'private': 'hidden'}}
        evidence = []
        observe_response(response, evidence)
        self.assertEqual(evidence, [{'kind': 'user_self', 'http_status': 200, '0_status_code': 8,
                                    'explicit_login_required': True, 'explicit_session_expired': False}])

    def test_transport_reports_booleans_not_values(self):
        request = MagicMock()
        request.url = 'https://www.douyin.com/chat?private=data'
        request.header_value.return_value = 'sessionid=private; other=hidden'
        evidence = {}
        observe_request(request, evidence)
        self.assertEqual(evidence, {'chat_document_observed': True, 'chat_document_session_sent': True})
        request.url = 'https://example.com/chat'
        request.header_value.reset_mock()
        observe_request(request, evidence)
        request.header_value.assert_not_called()

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
        self.assertEqual(records[-1], {'stage': 'reload', 'ready': False, 'error_type': 'RuntimeError', 'redacted_screenshot': True})
        self.assertIn('mask', context.new_page.return_value.screenshot.call_args.kwargs)
        self.assertEqual(context.new_page.call_count, 1)

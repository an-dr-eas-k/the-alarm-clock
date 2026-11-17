import json
import ssl
import unittest
from unittest import mock

from utils import network
from utils.network import json_api


def make_response(status=200, body=b"", readable=True):
    response = mock.Mock()
    response.getcode.return_value = status
    response.readable.return_value = readable
    response.read.return_value = body
    return response


class JsonApiTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(network, "urlopen")
        self.urlopen = patcher.start()
        self.addCleanup(patcher.stop)
        logger_patcher = mock.patch.object(network, "logger")
        self.logger = logger_patcher.start()
        self.addCleanup(logger_patcher.stop)

    def test_returns_parsed_json_on_success(self):
        self.urlopen.return_value = make_response(body=b'{"a": 1, "b": [1, 2]}')
        self.assertEqual(json_api("http://x/y"), {"a": 1, "b": [1, 2]})

    def test_returns_true_when_body_is_empty(self):
        self.urlopen.return_value = make_response(body=b"")
        self.assertIs(json_api("http://x/y"), True)

    def test_returns_true_when_response_not_readable(self):
        self.urlopen.return_value = make_response(readable=False)
        self.assertIs(json_api("http://x/y"), True)

    def test_non_200_status_returns_false_and_logs_error(self):
        self.urlopen.return_value = make_response(status=500, body=b"oops")
        self.assertIs(json_api("http://x/y"), False)
        self.logger.error.assert_called_once()

    def test_network_exception_returns_false_and_logs_error(self):
        self.urlopen.side_effect = OSError("unreachable")
        self.assertIs(json_api("http://x/y"), False)
        self.logger.error.assert_called_once()

    def test_invalid_json_body_raises_value_error(self):
        self.urlopen.return_value = make_response(body=b"<html>")
        with self.assertRaises(json.JSONDecodeError):
            json_api("http://x/y")

    def test_request_carries_url_default_headers_and_no_data(self):
        self.urlopen.return_value = make_response(body=b"{}")
        json_api("http://example.com/api")

        request = self.urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://example.com/api")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertIsNone(request.data)
        self.assertEqual(request.get_method(), "GET")

    def test_data_bytes_turn_request_into_post_with_custom_headers(self):
        self.urlopen.return_value = make_response(body=b"{}")
        json_api("http://example.com/api", {"X-Test": "1"}, b'{"k": "v"}')

        request = self.urlopen.call_args.args[0]
        self.assertEqual(request.data, b'{"k": "v"}')
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("X-test"), "1")

    def test_ssl_verification_is_disabled_in_context(self):
        self.urlopen.return_value = make_response(body=b"{}")
        json_api("https://example.com")

        context = self.urlopen.call_args.kwargs["context"]
        self.assertIsInstance(context, ssl.SSLContext)
        self.assertFalse(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_NONE)

    def test_json_scalar_zero_is_returned_as_is(self):
        self.urlopen.return_value = make_response(body=b"0")
        self.assertEqual(json_api("http://x/y"), 0)


if __name__ == "__main__":
    unittest.main()

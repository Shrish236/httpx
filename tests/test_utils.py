import json
import logging
import os
import random
import unittest

import pytest

import httpx
from httpx._utils import (
    URLPattern,
    get_environment_proxies,
    parse_retry_after_header,
)


@pytest.mark.parametrize(
    "encoding",
    (
        "utf-32",
        "utf-8-sig",
        "utf-16",
        "utf-8",
        "utf-16-be",
        "utf-16-le",
        "utf-32-be",
        "utf-32-le",
    ),
)
def test_encoded(encoding):
    content = '{"abc": 123}'.encode(encoding)
    response = httpx.Response(200, content=content)
    assert response.json() == {"abc": 123}


def test_bad_utf_like_encoding():
    content = b"\x00\x00\x00\x00"
    response = httpx.Response(200, content=content)
    with pytest.raises(json.decoder.JSONDecodeError):
        response.json()


@pytest.mark.parametrize(
    ("encoding", "expected"),
    (
        ("utf-16-be", "utf-16"),
        ("utf-16-le", "utf-16"),
        ("utf-32-be", "utf-32"),
        ("utf-32-le", "utf-32"),
    ),
)
def test_guess_by_bom(encoding, expected):
    content = '\ufeff{"abc": 123}'.encode(encoding)
    response = httpx.Response(200, content=content)
    assert response.json() == {"abc": 123}


def test_logging_request(server, caplog):
    caplog.set_level(logging.INFO)
    with httpx.Client() as client:
        response = client.get(server.url)
        assert response.status_code == 200

    assert caplog.record_tuples == [
        (
            "httpx",
            logging.INFO,
            'HTTP Request: GET http://127.0.0.1:8000/ "HTTP/1.1 200 OK"',
        )
    ]


def test_logging_redirect_chain(server, caplog):
    caplog.set_level(logging.INFO)
    with httpx.Client(follow_redirects=True) as client:
        response = client.get(server.url.copy_with(path="/redirect_301"))
        assert response.status_code == 200

    assert caplog.record_tuples == [
        (
            "httpx",
            logging.INFO,
            "HTTP Request: GET http://127.0.0.1:8000/redirect_301"
            ' "HTTP/1.1 301 Moved Permanently"',
        ),
        (
            "httpx",
            logging.INFO,
            'HTTP Request: GET http://127.0.0.1:8000/ "HTTP/1.1 200 OK"',
        ),
    ]


@pytest.mark.parametrize(
    ["environment", "proxies"],
    [
        ({}, {}),
        ({"HTTP_PROXY": "http://127.0.0.1"}, {"http://": "http://127.0.0.1"}),
        (
            {"https_proxy": "http://127.0.0.1", "HTTP_PROXY": "https://127.0.0.1"},
            {"https://": "http://127.0.0.1", "http://": "https://127.0.0.1"},
        ),
        ({"all_proxy": "http://127.0.0.1"}, {"all://": "http://127.0.0.1"}),
        ({"TRAVIS_APT_PROXY": "http://127.0.0.1"}, {}),
        ({"no_proxy": "127.0.0.1"}, {"all://127.0.0.1": None}),
        ({"no_proxy": "192.168.0.0/16"}, {"all://192.168.0.0/16": None}),
        ({"no_proxy": "::1"}, {"all://[::1]": None}),
        ({"no_proxy": "localhost"}, {"all://localhost": None}),
        ({"no_proxy": "github.com"}, {"all://*github.com": None}),
        ({"no_proxy": ".github.com"}, {"all://*.github.com": None}),
        ({"no_proxy": "http://github.com"}, {"http://github.com": None}),
    ],
)
def test_get_environment_proxies(environment, proxies):
    os.environ.update(environment)

    assert get_environment_proxies() == proxies


@pytest.mark.parametrize(
    ["pattern", "url", "expected"],
    [
        ("http://example.com", "http://example.com", True),
        ("http://example.com", "https://example.com", False),
        ("http://example.com", "http://other.com", False),
        ("http://example.com:123", "http://example.com:123", True),
        ("http://example.com:123", "http://example.com:456", False),
        ("http://example.com:123", "http://example.com", False),
        ("all://example.com", "http://example.com", True),
        ("all://example.com", "https://example.com", True),
        ("http://", "http://example.com", True),
        ("http://", "https://example.com", False),
        ("all://", "https://example.com:123", True),
        ("", "https://example.com:123", True),
    ],
)
def test_url_matches(pattern, url, expected):
    pattern = URLPattern(pattern)
    assert pattern.matches(httpx.URL(url)) == expected


def test_pattern_priority():
    matchers = [
        URLPattern("all://"),
        URLPattern("http://"),
        URLPattern("http://example.com"),
        URLPattern("http://example.com:123"),
    ]
    random.shuffle(matchers)
    assert sorted(matchers) == [
        URLPattern("http://example.com:123"),
        URLPattern("http://example.com"),
        URLPattern("http://"),
        URLPattern("all://"),
    ]


class TestParseRetryAfterHeader(unittest.TestCase):
    """Tests for parse_retry_after_header."""

    def setUp(self):
        self._logger = logging.getLogger("httpx._utils")
        self._original_disabled = self._logger.disabled
        self._original_level = self._logger.level
        self._logger.disabled = False

    def tearDown(self):
        self._logger.disabled = self._original_disabled
        self._logger.setLevel(self._original_level)

    def test_valid_integer_seconds(self):
        with self.assertNoLogs(self._logger, level=logging.WARNING):
            result = parse_retry_after_header("120")  # type: ignore
        self.assertEqual(result, 120.0)
        self.assertIsInstance(result, float)

    def test_valid_float_seconds(self):
        with self.assertNoLogs(self._logger, level=logging.WARNING):
            result = parse_retry_after_header("1.5")  # type: ignore
        self.assertEqual(result, 1.5)
        self.assertIsInstance(result, float)

    def test_valid_zero(self):
        with self.assertNoLogs(self._logger, level=logging.WARNING):
            result = parse_retry_after_header("0")  # type: ignore
        self.assertEqual(result, 0.0)
        self.assertIsInstance(result, float)

    def test_valid_whitespace_padded(self):
        with self.assertNoLogs(self._logger, level=logging.WARNING):
            result = parse_retry_after_header("  42.25  ")  # type: ignore
        self.assertEqual(result, 42.25)
        self.assertIsInstance(result, float)

    def test_negative_number_returns_none_and_warns(self):
        for raw in ("-1", "-0.5"):
            with self.subTest(raw=raw):
                with self.assertLogs(self._logger, level=logging.WARNING) as cm:
                    result = parse_retry_after_header(raw)  # type: ignore
                self.assertIsNone(result)
                self.assertEqual(len(cm.output), 1)
                self.assertIn("Invalid Retry-After header value", cm.output[0])

    def test_non_finite_values_return_none_and_warn(self):
        for raw in ("nan", "inf", "-inf", "Infinity"):
            with self.subTest(raw=raw):
                with self.assertLogs(self._logger, level=logging.WARNING) as cm:
                    result = parse_retry_after_header(raw)  # type: ignore
                self.assertIsNone(result)
                self.assertEqual(len(cm.output), 1)
                self.assertIn("Invalid Retry-After header value", cm.output[0])

    def test_invalid_inputs_return_none_and_warn(self):
        for raw in ("", "   ", "abc", "Wed, 21 Oct 2015 07:28:00 GMT", None, True):
            with self.subTest(raw=raw):
                with self.assertLogs(self._logger, level=logging.WARNING) as cm:
                    result = parse_retry_after_header(raw)  # type: ignore
                self.assertIsNone(result)
                self.assertEqual(len(cm.output), 1)
                self.assertIn("Invalid Retry-After header value", cm.output[0])

    def test_transient_error_succeeds_within_three_attempts(self):
        class FlakyHeaderValue:
            """Header value that fails transiently before returning a float."""

            def __init__(self, failures, result):
                self.failures = failures
                self.result = result
                self.calls = 0

            def __float__(self):
                self.calls += 1
                if self.calls <= self.failures:
                    raise RuntimeError("transient parse error")
                return self.result

        value = FlakyHeaderValue(failures=2, result=15.0)  # type: ignore
        with self.assertNoLogs(self._logger, level=logging.WARNING):
            result = parse_retry_after_header(value)  # type: ignore
        self.assertEqual(result, 15.0)
        self.assertIsInstance(result, float)
        self.assertEqual(value.calls, 3)

    def test_transient_error_exhausts_three_attempts_and_warns(self):
        class AlwaysFailingHeaderValue:
            """Header value that always fails when converted to float."""

            def __init__(self):
                self.calls = 0

            def __float__(self):
                self.calls += 1
                raise RuntimeError("persistent parse error")

        value = AlwaysFailingHeaderValue()  # type: ignore
        with self.assertLogs(self._logger, level=logging.WARNING) as cm:
            result = parse_retry_after_header(value)  # type: ignore
        self.assertIsNone(result)
        self.assertEqual(value.calls, 3)
        self.assertEqual(len(cm.output), 1)
        self.assertIn("Invalid Retry-After header value", cm.output[0])

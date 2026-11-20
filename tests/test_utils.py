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
    parse_content_length_header,
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


class TestParseContentLengthHeader(unittest.TestCase):
    """Tests for parse_content_length_header."""

    def setUp(self):
        self._logger = logging.getLogger("httpx._utils")
        self._orig_disabled = self._logger.disabled
        self._orig_filters = list(self._logger.filters)
        self._orig_manager_disable = logging.root.manager.disable
        self._logger.disabled = False
        self._logger.filters.clear()
        logging.disable(logging.NOTSET)

    def tearDown(self):
        self._logger.disabled = self._orig_disabled
        self._logger.filters[:] = self._orig_filters
        logging.disable(self._orig_manager_disable)

    def test_valid_values(self):
        for raw, expected in [
            ("0", 0),
            ("42", 42),
            (" 123 ", 123),
            (0, 0),
            (100, 100),
            (b"256", 256),
        ]:
            with self.subTest(raw=raw):
                with self.assertNoLogs(self._logger, level=logging.WARNING):
                    result = parse_content_length_header(raw)
                self.assertEqual(result, expected)

    def test_missing_value(self):
        with self.assertNoLogs(self._logger, level=logging.WARNING):
            result = parse_content_length_header(None)
        self.assertIsNone(result)

    def test_negative_values(self):
        for raw in ("-1", "-100", -5):
            with self.subTest(raw=raw):
                with self.assertLogs(self._logger, level=logging.WARNING) as cm:
                    result = parse_content_length_header(raw)
                self.assertIsNone(result)
                self.assertEqual(len(cm.output), 1)
                self.assertIn("Invalid Content-Length header value", cm.output[0])

    def test_non_numeric_and_invalid_values(self):
        for raw in ("", "   ", "abc", "12.34", "123abc", 12.5, True, object()):
            with self.subTest(raw=raw):
                with self.assertLogs(self._logger, level=logging.WARNING) as cm:
                    result = parse_content_length_header(raw)
                self.assertIsNone(result)
                self.assertEqual(len(cm.output), 1)
                self.assertIn("Invalid Content-Length header value", cm.output[0])

    def test_retries_transient_error_and_succeeds(self):
        class FlakyHeaderValue:
            """Header value that fails transiently before succeeding."""

            def __init__(self):
                self.attempts = 0

            def __int__(self):
                self.attempts += 1
                if self.attempts < 3:
                    raise RuntimeError("transient error")
                return 128

        raw = FlakyHeaderValue()
        with self.assertNoLogs(self._logger, level=logging.WARNING):
            result = parse_content_length_header(raw)
        self.assertEqual(result, 128)
        self.assertEqual(raw.attempts, 3)

    def test_retries_exhausted_logs_warning(self):
        class AlwaysFailingHeaderValue:
            """Header value that always fails with a transient error."""

            def __init__(self):
                self.attempts = 0

            def __int__(self):
                self.attempts += 1
                raise RuntimeError("transient error")

        raw = AlwaysFailingHeaderValue()
        with self.assertLogs(self._logger, level=logging.WARNING) as cm:
            result = parse_content_length_header(raw)
        self.assertIsNone(result)
        self.assertEqual(raw.attempts, 3)
        self.assertEqual(len(cm.output), 1)
        self.assertIn("Invalid Content-Length header value", cm.output[0])

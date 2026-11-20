import json
import logging
import os
import random
import unittest

import pytest

import httpx
from httpx._utils import URLPattern, get_environment_proxies, parse_keep_alive_timeout


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


class TestParseKeepAliveTimeout(unittest.TestCase):
    """Tests for parse_keep_alive_timeout."""

    def test_valid_timeout_with_max(self):
        self.assertEqual(parse_keep_alive_timeout("timeout=5, max=100"), 5.0)

    def test_valid_timeout_only(self):
        self.assertEqual(parse_keep_alive_timeout("timeout=10"), 10.0)

    def test_valid_timeout_float(self):
        self.assertEqual(parse_keep_alive_timeout("max=50, timeout=2.5"), 2.5)

    def test_valid_timeout_case_insensitive_and_whitespace(self):
        self.assertEqual(parse_keep_alive_timeout("  TIMEOUT = 15 , MAX = 20 "), 15.0)

    def test_valid_timeout_quoted(self):
        self.assertEqual(parse_keep_alive_timeout('timeout="7", max=100'), 7.0)

    def test_valid_timeout_zero(self):
        self.assertEqual(parse_keep_alive_timeout("timeout=0"), 0.0)

    def test_missing_timeout_returns_none(self):
        self.assertIsNone(parse_keep_alive_timeout("max=100"))

    def test_empty_header_returns_none(self):
        self.assertIsNone(parse_keep_alive_timeout(""))
        self.assertIsNone(parse_keep_alive_timeout("   "))

    def test_invalid_timeout_value_logs_warning(self):
        with self.assertLogs("httpx", level="WARNING") as cm:
            result = parse_keep_alive_timeout("timeout=abc, max=100")
        self.assertIsNone(result)
        self.assertTrue(len(cm.output) >= 1)

    def test_negative_timeout_logs_warning(self):
        with self.assertLogs("httpx", level="WARNING") as cm:
            result = parse_keep_alive_timeout("timeout=-5")
        self.assertIsNone(result)
        self.assertTrue(len(cm.output) >= 1)

    def test_non_finite_timeout_logs_warning(self):
        for value in ("timeout=inf", "timeout=nan"):
            with self.assertLogs("httpx", level="WARNING") as cm:
                result = parse_keep_alive_timeout(value)
            self.assertIsNone(result)
            self.assertTrue(len(cm.output) >= 1)

    def test_malformed_header_logs_warning(self):
        with self.assertLogs("httpx", level="WARNING") as cm:
            result = parse_keep_alive_timeout("not-a-valid-header")
        self.assertIsNone(result)
        self.assertTrue(len(cm.output) >= 1)

    def test_non_string_input_logs_warning(self):
        with self.assertLogs("httpx", level="WARNING") as cm:
            result = parse_keep_alive_timeout(None)
        self.assertIsNone(result)
        self.assertTrue(len(cm.output) >= 1)

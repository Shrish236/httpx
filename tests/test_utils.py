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
    is_retryable_status_code,
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


class TestIsRetryableStatusCode(unittest.TestCase):
    """Tests for is_retryable_status_code."""

    def test_retryable_429(self):
        with self.assertNoLogs("httpx._utils", level=logging.WARNING):
            self.assertIs(is_retryable_status_code(429), True)  # type: ignore

    def test_retryable_5xx(self):
        with self.assertNoLogs("httpx._utils", level=logging.WARNING):
            for code in (500, 502, 503, 504, 599):
                self.assertIs(
                    is_retryable_status_code(code),  # type: ignore
                    True,
                    msg=f"expected status code {code} to be retryable",
                )

    def test_non_retryable_status_codes(self):
        with self.assertNoLogs("httpx._utils", level=logging.WARNING):
            for code in (100, 200, 204, 301, 400, 404, 428, 430, 499):
                self.assertIs(
                    is_retryable_status_code(code),  # type: ignore
                    False,
                    msg=f"expected status code {code} not to be retryable",
                )

    def test_invalid_types(self):
        for invalid in ("500", None, 500.0, True, False, [500]):
            with self.assertLogs("httpx._utils", level=logging.WARNING) as cm:
                result = is_retryable_status_code(invalid)  # type: ignore
            self.assertIsNone(result, msg=f"expected None for {invalid!r}")
            self.assertEqual(len(cm.output), 1)
            self.assertIn("Invalid HTTP status code", cm.output[0])

    def test_out_of_range_status_codes(self):
        for invalid in (-1, 0, 99, 600, 1000):
            with self.assertLogs("httpx._utils", level=logging.WARNING) as cm:
                result = is_retryable_status_code(invalid)  # type: ignore
            self.assertIsNone(result, msg=f"expected None for {invalid!r}")
            self.assertEqual(len(cm.output), 1)
            self.assertIn("Invalid HTTP status code", cm.output[0])

    def test_retries_on_transient_error_then_succeeds(self):
        class TransientStatusCode(int):
            """Int subclass that raises transiently on __int__."""

            fail_times = 2
            attempts = 0

            def __int__(self):
                self.attempts += 1
                if self.attempts <= self.fail_times:
                    raise RuntimeError("transient error")
                return super().__int__()

        code = TransientStatusCode(503)
        code.attempts = 0
        with self.assertNoLogs("httpx._utils", level=logging.WARNING):
            self.assertIs(is_retryable_status_code(code), True)  # type: ignore
        self.assertEqual(code.attempts, 3)

    def test_gives_up_after_three_transient_errors(self):
        class AlwaysFailingStatusCode(int):
            """Int subclass that always raises on __int__."""

            attempts = 0

            def __int__(self):
                self.attempts += 1
                raise RuntimeError("transient error")

        code = AlwaysFailingStatusCode(503)
        code.attempts = 0
        with self.assertLogs("httpx._utils", level=logging.WARNING) as cm:
            result = is_retryable_status_code(code)  # type: ignore
        self.assertIsNone(result)
        self.assertEqual(code.attempts, 3)
        self.assertEqual(len(cm.output), 1)
        self.assertIn("Invalid HTTP status code", cm.output[0])

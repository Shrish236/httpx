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
    parse_content_range_header,
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


class TestParseContentRangeHeader(unittest.TestCase):
    """Tests for parse_content_range_header."""

    def setUp(self):
        logger = logging.getLogger("httpx._utils")
        prev_disabled = logger.disabled
        prev_manager_disable = logging.root.manager.disable
        logger.disabled = False
        logging.disable(logging.NOTSET)
        self.addCleanup(setattr, logger, "disabled", prev_disabled)
        self.addCleanup(logging.disable, prev_manager_disable)

    def test_valid_headers(self):
        cases = [
            ("bytes 0-499/1234", (0, 499, 1234)),
            ("bytes 0-0/1", (0, 0, 1)),
            ("bytes 0-499/500", (0, 499, 500)),
            ("  bytes 10-20/100  ", (10, 20, 100)),
        ]
        for header, expected in cases:
            with self.subTest(header=header):
                with self.assertNoLogs("httpx._utils", level="WARNING"):
                    result = parse_content_range_header(header)  # type: ignore
                self.assertEqual(result, expected)

    def test_invalid_format_returns_none_and_warns(self):
        invalid_headers = [
            "",
            "invalid",
            "items 0-499/1234",
            "bytes 0-499/*",
            "bytes */1234",
            "bytes -1-10/100",
            "bytes a-b/c",
            None,
        ]
        for header in invalid_headers:
            with self.subTest(header=header):
                with self.assertLogs("httpx._utils", level="WARNING") as cm:
                    result = parse_content_range_header(header)  # type: ignore
                self.assertIsNone(result)
                self.assertTrue(
                    any("Invalid Content-Range header" in msg for msg in cm.output)
                )

    def test_invalid_bounds_returns_none_and_warns(self):
        invalid_headers = [
            "bytes 500-499/1234",
            "bytes 0-1234/1234",
            "bytes 0-2000/1234",
            "bytes 0-0/0",
        ]
        for header in invalid_headers:
            with self.subTest(header=header):
                with self.assertLogs("httpx._utils", level="WARNING") as cm:
                    result = parse_content_range_header(header)  # type: ignore
                self.assertIsNone(result)
                self.assertTrue(
                    any("Invalid Content-Range header" in msg for msg in cm.output)
                )

    def test_retries_on_transient_error_and_succeeds(self):
        class FlakyHeader:
            """Header-like object that fails twice before returning a valid value."""

            def __init__(self):
                self.calls = 0

            def strip(self):
                self.calls += 1
                if self.calls < 3:
                    raise RuntimeError("transient error")
                return "bytes 0-499/1234"

        flaky = FlakyHeader()  # type: ignore
        with self.assertNoLogs("httpx._utils", level="WARNING"):
            result = parse_content_range_header(flaky)  # type: ignore
        self.assertEqual(result, (0, 499, 1234))
        self.assertEqual(flaky.calls, 3)

    def test_exhausts_retries_returns_none_and_warns(self):
        class AlwaysFailingHeader:
            """Header-like object that raises a transient error on every attempt."""

            def __init__(self):
                self.calls = 0

            def strip(self):
                self.calls += 1
                raise RuntimeError("transient error")

        failing = AlwaysFailingHeader()  # type: ignore
        with self.assertLogs("httpx._utils", level="WARNING") as cm:
            result = parse_content_range_header(failing)  # type: ignore
        self.assertIsNone(result)
        self.assertEqual(failing.calls, 3)
        self.assertEqual(len(cm.output), 1)
        self.assertIn("Invalid Content-Range header", cm.output[0])

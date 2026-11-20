import datetime
import email.utils
import json
import logging
import os
import random

import pytest

import httpx
from httpx._utils import URLPattern, get_environment_proxies, parse_retry_after


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


@pytest.mark.parametrize(
    ["value", "expected"],
    [
        ("0", 0.0),
        ("120", 120.0),
        ("  42  ", 42.0),
        ("-5", None),
        ("12.5", None),
        ("", None),
        ("   ", None),
        ("invalid", None),
        ("Wed, 99 Oct 2015 07:28:00 GMT", None),
        ("²", None),
        ("9" * 400, None),
        ("Wed, 21 Oct 2015 07:28:00 GMT", 0.0),
        ("  Wed, 21 Oct 2015 07:28:00 GMT  ", 0.0),
        ("Sunday, 06-Nov-94 08:49:37 GMT", 0.0),
        ("Sun Nov  6 08:49:37 1994", 0.0),
    ],
)
def test_parse_retry_after_values(value, expected):
    result = parse_retry_after(value)
    assert result == expected
    if expected is not None:
        assert isinstance(result, float)


def test_parse_retry_after_future_http_date():
    future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        seconds=120
    )
    header = email.utils.format_datetime(future, usegmt=True)
    result = parse_retry_after(header)
    assert result is not None
    assert result == pytest.approx(120.0, abs=2.0)


def test_parse_retry_after_future_asctime_date():
    future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        seconds=60
    )
    # ANSI C asctime() format without timezone (assumed UTC per RFC 9110)
    header = future.strftime("%a %b %d %H:%M:%S %Y")
    result = parse_retry_after(header)
    assert result is not None
    assert result == pytest.approx(60.0, abs=2.0)


def test_parse_retry_after_future_rfc850_date():
    future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        seconds=90
    )
    header = future.strftime("%A, %d-%b-%y %H:%M:%S GMT")
    result = parse_retry_after(header)
    assert result is not None
    assert result == pytest.approx(90.0, abs=2.0)


def test_parse_retry_after_future_with_timezone_offset():
    tz_plus_2 = datetime.timezone(datetime.timedelta(hours=2))
    future = datetime.datetime.now(tz_plus_2) + datetime.timedelta(seconds=75)
    header = email.utils.format_datetime(future)
    result = parse_retry_after(header)
    assert result is not None
    assert result == pytest.approx(75.0, abs=2.0)

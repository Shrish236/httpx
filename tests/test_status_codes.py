import httpx


def test_status_code_as_int():
    # mypy doesn't (yet) recognize that IntEnum members are ints, so ignore it here
    assert httpx.codes.NOT_FOUND == 404  # type: ignore[comparison-overlap]
    assert str(httpx.codes.NOT_FOUND) == "404"


def test_status_code_value_lookup():
    assert httpx.codes(404) == 404


def test_status_code_phrase_lookup():
    assert httpx.codes["NOT_FOUND"] == 404


def test_lowercase_status_code():
    assert httpx.codes.not_found == 404  # type: ignore


def test_reason_phrase_for_status_code():
    assert httpx.codes.get_reason_phrase(404) == "Not Found"


def test_reason_phrase_for_unknown_status_code():
    assert httpx.codes.get_reason_phrase(499) == ""


def test_is_permanent_redirect():
    assert httpx.codes.is_permanent_redirect(301) is True
    assert httpx.codes.is_permanent_redirect(308) is True
    assert httpx.codes.is_permanent_redirect(302) is False
    assert httpx.codes.is_permanent_redirect(307) is False
    assert httpx.codes.is_permanent_redirect(200) is False

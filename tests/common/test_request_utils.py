"""请求来源 IP 归一化与信任边界测试。"""

from starlette.requests import Request

from app.utils.request import get_client_ip


def _request(
    forwarded_for: str | None = None,
    *,
    client_host: str | None = "198.51.100.10",
) -> Request:
    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode("ascii")))

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers,
        "client": (client_host, 12345) if client_host is not None else None,
    }
    return Request(scope)


def test_get_client_ip_uses_first_valid_forwarded_address() -> None:
    assert get_client_ip(_request("203.0.113.7, 10.0.0.1")) == "203.0.113.7"


def test_get_client_ip_normalizes_ipv6() -> None:
    assert get_client_ip(_request("2001:0db8:0:0:0:0:0:1")) == "2001:db8::1"


def test_get_client_ip_falls_back_when_forwarded_address_is_invalid() -> None:
    assert get_client_ip(_request("not-an-ip")) == "198.51.100.10"


def test_get_client_ip_rejects_overlong_forwarded_value() -> None:
    assert get_client_ip(_request("1" * 200)) == "198.51.100.10"


def test_get_client_ip_rejects_ipv6_scope_identifier() -> None:
    assert get_client_ip(_request("fe80::1%untrusted-zone")) == "198.51.100.10"


def test_get_client_ip_returns_unknown_when_no_source_is_valid() -> None:
    assert get_client_ip(_request("not-an-ip", client_host="test-client")) == "unknown"

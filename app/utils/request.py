"""请求工具函数。"""

from ipaddress import ip_address

from fastapi import Request

_IP_ADDRESS_MAX_LENGTH = 45


def _normalize_ip(value: str | None) -> str | None:
    """返回规范化的 IPv4/IPv6；无效输入返回 ``None``。"""
    if value is None:
        return None

    candidate = value.strip()
    if (
        not candidate
        or len(candidate) > _IP_ADDRESS_MAX_LENGTH
        or "%" in candidate
    ):
        return None

    try:
        normalized = str(ip_address(candidate))
    except ValueError:
        return None
    return normalized if len(normalized) <= _IP_ADDRESS_MAX_LENGTH else None


def get_client_ip(request: Request) -> str:
    """获取用于审计的合法客户端 IP。

    优先读取 ``X-Forwarded-For`` 的第一个地址，再回退到直连 IP。
    部署层仍需确保只有受信任的反向代理能够覆盖转发头。
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        normalized_forwarded = _normalize_ip(forwarded.split(",", maxsplit=1)[0])
        if normalized_forwarded is not None:
            return normalized_forwarded

    direct_ip = _normalize_ip(request.client.host if request.client else None)
    return direct_ip if direct_ip is not None else "unknown"

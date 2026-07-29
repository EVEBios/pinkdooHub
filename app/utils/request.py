"""请求工具函数。"""

from fastapi import Request


def get_client_ip(request: Request) -> str:
    """获取客户端真实 IP。

    优先读取 X-Forwarded-For（Nginx 代理场景），
    fallback 到直连 IP。
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

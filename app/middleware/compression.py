"""只对 API/文本响应启用的 gzip 中间件。"""

from collections.abc import Iterable
from decimal import Decimal, InvalidOperation

from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send


class SelectiveGZipMiddleware:
    """压缩文本路由，同时绕过本地上传文件命名空间。"""

    def __init__(
        self,
        app: ASGIApp,
        *,
        minimum_size: int,
        compresslevel: int,
        excluded_path_prefixes: Iterable[str] = (),
    ) -> None:
        self.app = app
        self.gzip_app = GZipMiddleware(
            app,
            minimum_size=minimum_size,
            compresslevel=compresslevel,
        )
        self.excluded_path_prefixes = tuple(excluded_path_prefixes)

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        if path.startswith(self.excluded_path_prefixes) or not _accepts_gzip(
            scope
        ):
            await self.app(scope, receive, send)
            return

        # Starlette 当前仅以子串判断 gzip，既不处理 q=0，也区分值的大小写。
        # 先完成严格协商，再给其 responder 一个单一规范 token。
        gzip_scope = dict(scope)
        gzip_scope["headers"] = [
            (name, value)
            for name, value in scope.get("headers", ())
            if name.lower() != b"accept-encoding"
        ] + [(b"accept-encoding", b"gzip")]
        await self.gzip_app(gzip_scope, receive, send)


def _accepts_gzip(scope: Scope) -> bool:
    """仅在客户端以正质量值明确接受 gzip 时返回 True。"""

    qualities: list[Decimal] = []
    for name, raw_value in scope.get("headers", ()):
        if name.lower() != b"accept-encoding":
            continue
        for item in raw_value.decode("latin-1").split(","):
            coding, *parameters = item.split(";")
            if coding.strip().lower() != "gzip":
                continue
            quality = Decimal("1")
            for parameter in parameters:
                key, separator, value = parameter.partition("=")
                if key.strip().lower() != "q":
                    continue
                if not separator:
                    quality = Decimal("0")
                    break
                try:
                    quality = Decimal(value.strip())
                except InvalidOperation:
                    quality = Decimal("0")
                if not quality.is_finite() or quality < 0 or quality > 1:
                    quality = Decimal("0")
                break
            qualities.append(quality)
    return bool(qualities) and max(qualities) > 0

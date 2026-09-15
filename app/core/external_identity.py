"""外部平台标识的不可逆持久化键。"""

import hashlib
import hmac

from app.core.config import settings


def external_identity_key(provider: str, value: str) -> str:
    """用独立 Pepper 生成稳定 HMAC，避免持久化原始平台标识。"""

    return hmac.new(
        settings.external_identity_pepper.encode("utf-8"),
        f"{provider}:{value}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

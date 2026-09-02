"""登录会话签发边界。"""

import uuid

from app.core.redis import save_refresh_session
from app.core.security import create_access_token, create_refresh_token


async def issue_token_pair(*, user_id: int, auth_version: int) -> dict[str, str]:
    """为一次新登录创建独立 session family 和双 Token。"""

    session_id = uuid.uuid4().hex
    jti = uuid.uuid4().hex
    access_token = create_access_token(
        user_id,
        jti,
        session_id=session_id,
        auth_version=auth_version,
    )
    refresh_token = create_refresh_token(
        user_id,
        jti,
        session_id=session_id,
        auth_version=auth_version,
    )
    await save_refresh_session(jti, session_id, user_id)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
    }

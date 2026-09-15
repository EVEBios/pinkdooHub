"""桌台 Session 编号生成器。"""

import secrets
import time

from app.common.constants.table_session import (
    TABLE_SESSION_NO_CROCKFORD_ALPHABET,
    TABLE_SESSION_NO_PREFIX,
    TABLE_SESSION_NO_RANDOM_BYTES,
    TABLE_SESSION_NO_TIMESTAMP_BITS,
    TABLE_SESSION_NO_ULID_LENGTH,
)


def generate_table_session_number() -> str:
    """生成 ``TS`` + 26 位 Crockford Base32 ULID。"""

    timestamp_ms = time.time_ns() // 1_000_000
    if timestamp_ms >= 1 << TABLE_SESSION_NO_TIMESTAMP_BITS:
        raise OverflowError("Current timestamp exceeds the ULID 48-bit range")
    random_value = int.from_bytes(
        secrets.token_bytes(TABLE_SESSION_NO_RANDOM_BYTES),
        byteorder="big",
    )
    value = (timestamp_ms << (TABLE_SESSION_NO_RANDOM_BYTES * 8)) | random_value
    encoded = [TABLE_SESSION_NO_CROCKFORD_ALPHABET[0]] * TABLE_SESSION_NO_ULID_LENGTH
    for index in range(TABLE_SESSION_NO_ULID_LENGTH - 1, -1, -1):
        encoded[index] = TABLE_SESSION_NO_CROCKFORD_ALPHABET[value & 0b11111]
        value >>= 5
    return f"{TABLE_SESSION_NO_PREFIX}{''.join(encoded)}"

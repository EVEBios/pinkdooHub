"""Order 编号生成器。"""

import secrets
import time

from app.common.constants.order import (
    ORDER_NO_CROCKFORD_ALPHABET,
    ORDER_NO_PREFIX,
    ORDER_NO_RANDOM_BYTES,
    ORDER_NO_TIMESTAMP_BITS,
    ORDER_NO_ULID_LENGTH,
)


def generate_order_number() -> str:
    """生成 ``OD`` + 26 位 Crockford Base32 ULID 订单号。

    时间部分使用当前 UTC Unix 毫秒，随机部分来自操作系统密码学安全随机源。
    数据库 ``UNIQUE(order_no)`` 仍是并发唯一性的最终保证。
    """

    timestamp_ms = time.time_ns() // 1_000_000
    if timestamp_ms >= 1 << ORDER_NO_TIMESTAMP_BITS:
        raise OverflowError("Current timestamp exceeds the ULID 48-bit range")

    random_value = int.from_bytes(
        secrets.token_bytes(ORDER_NO_RANDOM_BYTES),
        byteorder="big",
    )
    value = (timestamp_ms << (ORDER_NO_RANDOM_BYTES * 8)) | random_value

    encoded = [ORDER_NO_CROCKFORD_ALPHABET[0]] * ORDER_NO_ULID_LENGTH
    for index in range(ORDER_NO_ULID_LENGTH - 1, -1, -1):
        encoded[index] = ORDER_NO_CROCKFORD_ALPHABET[value & 0b11111]
        value >>= 5

    return f"{ORDER_NO_PREFIX}{''.join(encoded)}"

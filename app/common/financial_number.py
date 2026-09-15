"""Payment、Recharge 与 Refund 的统一 ULID 编号生成器。"""

import secrets
import time

from app.common.constants.order import (
    ORDER_NO_CROCKFORD_ALPHABET,
    ORDER_NO_RANDOM_BYTES,
    ORDER_NO_TIMESTAMP_BITS,
    ORDER_NO_ULID_LENGTH,
)


def generate_financial_number(prefix: str) -> str:
    """生成两位前缀加 26 位 Crockford Base32 ULID。"""

    if len(prefix) != 2 or not prefix.isascii() or not prefix.isalpha():
        raise ValueError("Financial number prefix must be two ASCII letters")

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
    return f"{prefix.upper()}{''.join(encoded)}"


def generate_payment_number() -> str:
    return generate_financial_number("PY")


def generate_recharge_number() -> str:
    return generate_financial_number("RC")


def generate_refund_number() -> str:
    return generate_financial_number("RF")

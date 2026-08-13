"""Order 编号生成器契约测试。"""

import re

from pytest import MonkeyPatch

from app.common.constants.order import (
    ORDER_NO_LENGTH,
    ORDER_NO_PATTERN,
    ORDER_NO_RANDOM_BYTES,
)
from app.common.order_number import generate_order_number


def test_order_number_matches_frozen_format() -> None:
    """生成结果必须是 OD + 26 位大写 Crockford Base32。"""

    order_no = generate_order_number()

    assert len(order_no) == ORDER_NO_LENGTH
    assert re.fullmatch(ORDER_NO_PATTERN, order_no)


def test_order_number_uses_utc_milliseconds_and_secure_randomness(
    monkeypatch: MonkeyPatch,
) -> None:
    """ULID 的 48 位时间和 80 位随机数据应来自冻结的数据源。"""

    timestamp_ms = 1_700_000_000_123
    random_bytes = bytes.fromhex("00112233445566778899")
    requested_sizes: list[int] = []

    monkeypatch.setattr(
        "app.common.order_number.time.time_ns",
        lambda: timestamp_ms * 1_000_000,
    )

    def fake_token_bytes(size: int) -> bytes:
        requested_sizes.append(size)
        return random_bytes

    monkeypatch.setattr(
        "app.common.order_number.secrets.token_bytes",
        fake_token_bytes,
    )

    order_no = generate_order_number()

    assert order_no == "OD01HF7YAT3V008J4CT4ANK7F24S"
    assert requested_sizes == [ORDER_NO_RANDOM_BYTES]


def test_order_number_is_lexically_sortable_by_millisecond(
    monkeypatch: MonkeyPatch,
) -> None:
    """随机部分相同时，较晚毫秒生成的编号应按字典序更大。"""

    timestamps = iter((1_700_000_000_000, 1_700_000_000_001))
    monkeypatch.setattr(
        "app.common.order_number.time.time_ns",
        lambda: next(timestamps) * 1_000_000,
    )
    monkeypatch.setattr(
        "app.common.order_number.secrets.token_bytes",
        lambda _: bytes(ORDER_NO_RANDOM_BYTES),
    )

    first = generate_order_number()
    second = generate_order_number()

    assert first < second


def test_same_millisecond_uses_fresh_random_bytes(monkeypatch: MonkeyPatch) -> None:
    """同一毫秒内的调用不得复用进程内随机状态。"""

    random_values = iter(
        (
            bytes(ORDER_NO_RANDOM_BYTES),
            b"\x00" * (ORDER_NO_RANDOM_BYTES - 1) + b"\x01",
        )
    )
    monkeypatch.setattr(
        "app.common.order_number.time.time_ns",
        lambda: 1_700_000_000_000 * 1_000_000,
    )
    monkeypatch.setattr(
        "app.common.order_number.secrets.token_bytes",
        lambda _: next(random_values),
    )

    assert generate_order_number() != generate_order_number()


def test_order_number_rejects_timestamp_outside_ulid_range(
    monkeypatch: MonkeyPatch,
) -> None:
    """超过 ULID 48 位时间范围时应明确失败，而不是截断碰撞。"""

    monkeypatch.setattr(
        "app.common.order_number.time.time_ns",
        lambda: (1 << 48) * 1_000_000,
    )

    try:
        generate_order_number()
    except OverflowError as exc:
        assert str(exc) == "Current timestamp exceeds the ULID 48-bit range"
    else:
        raise AssertionError("Expected ULID timestamp overflow")

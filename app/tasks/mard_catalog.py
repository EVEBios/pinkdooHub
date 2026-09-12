"""MARD 221 冻结清单与确定性色板的运行时无关契约。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import struct
from typing import Final
import zlib


SOURCE_URL: Final = "https://peiseka.com/pindouseka.html"
EXPECTED_COLOR_COUNT: Final = 221
SERIES_COUNTS: Final[tuple[tuple[str, int], ...]] = (
    ("A", 26),
    ("B", 32),
    ("C", 29),
    ("D", 26),
    ("E", 24),
    ("F", 25),
    ("G", 21),
    ("H", 23),
    ("M", 15),
)
SWATCH_WIDTH: Final = 256
SWATCH_HEIGHT: Final = 256
PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"
PNG_END: Final = b"\x00\x00\x00\x00IEND\xaeB`\x82"


class MardCatalogError(RuntimeError):
    """冻结清单或确定性色板不满足契约。"""


@dataclass(frozen=True, slots=True)
class ManifestColor:
    slot_no: int
    color_code: str
    name: str
    sort: int
    is_active: bool
    hex: str
    rgb: tuple[int, int, int]
    image_filename: str


def expected_codes() -> tuple[str, ...]:
    """返回来源页冻结的 A1–M15 权威顺序。"""

    return tuple(
        f"{series}{number}"
        for series, count in SERIES_COUNTS
        for number in range(1, count + 1)
    )


def image_filename(*, color_code: str, hex_value: str) -> str:
    """生成与 Product 本地存储兼容的确定性 PNG key。"""

    identity = (
        f"pinkdoohub:mard-221:{color_code}:{hex_value}:"
        f"{SWATCH_WIDTH}x{SWATCH_HEIGHT}:png"
    )
    digest = hashlib.sha256(identity.encode("ascii")).hexdigest()
    return f"{digest[:32]}.png"


def _full_hex(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 7 or not value.startswith("#"):
        return False
    return all(character in "0123456789ABCDEF" for character in value[1:])


def load_manifest(path: Path) -> tuple[ManifestColor, ...]:
    """读取并严格验证版本化 MARD 221 清单。"""

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MardCatalogError("cannot read the MARD manifest") from error
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise MardCatalogError("manifest schema_version must be 1")
    source = document.get("source")
    if not isinstance(source, dict) or source.get("url") != SOURCE_URL:
        raise MardCatalogError("manifest source URL does not match MARD 221")
    if source.get("representation") != "css_rgb_swatch":
        raise MardCatalogError("manifest source representation is unsupported")
    if source.get("individual_image_files") is not False:
        raise MardCatalogError("manifest must describe CSS-rendered swatches")
    if document.get("swatch") != {
        "format": "png",
        "width": SWATCH_WIDTH,
        "height": SWATCH_HEIGHT,
        "color_space": "sRGB",
        "representation": "solid_color_generated_from_source_rgb",
    }:
        raise MardCatalogError("manifest swatch contract changed")

    raw_colors = document.get("colors")
    if not isinstance(raw_colors, list) or len(raw_colors) != EXPECTED_COLOR_COUNT:
        raise MardCatalogError(
            f"manifest must contain exactly {EXPECTED_COLOR_COUNT} colors"
        )

    colors: list[ManifestColor] = []
    codes = expected_codes()
    for expected_slot, raw in enumerate(raw_colors, start=1):
        if not isinstance(raw, dict):
            raise MardCatalogError(f"slot {expected_slot} is not an object")
        try:
            rgb_raw = raw["rgb"]
            if (
                not isinstance(rgb_raw, list)
                or len(rgb_raw) != 3
                or any(type(channel) is not int for channel in rgb_raw)
            ):
                raise ValueError
            color = ManifestColor(
                slot_no=raw["slot_no"],
                color_code=raw["color_code"],
                name=raw["name"],
                sort=raw["sort"],
                is_active=raw["is_active"],
                hex=raw["hex"],
                rgb=tuple(rgb_raw),
                image_filename=raw["image_filename"],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise MardCatalogError(
                f"slot {expected_slot} has an invalid shape"
            ) from error

        if type(color.slot_no) is not int or color.slot_no != expected_slot:
            raise MardCatalogError("manifest slots must be the ordered range 1..221")
        if color.color_code != codes[expected_slot - 1]:
            raise MardCatalogError(f"unexpected color code at slot {expected_slot}")
        if color.name != color.color_code:
            raise MardCatalogError("manifest name must equal its source color code")
        if type(color.sort) is not int or color.sort != expected_slot:
            raise MardCatalogError("manifest sort must match the frozen source order")
        if color.is_active is not True:
            raise MardCatalogError("all validated manifest colors must be active")
        if not _full_hex(color.hex):
            raise MardCatalogError(f"invalid HEX value at slot {expected_slot}")
        if any(channel < 0 or channel > 255 for channel in color.rgb):
            raise MardCatalogError(f"invalid RGB value at slot {expected_slot}")
        derived_hex = "#" + "".join(f"{channel:02X}" for channel in color.rgb)
        if derived_hex != color.hex:
            raise MardCatalogError(f"HEX and RGB differ at slot {expected_slot}")
        if color.image_filename != image_filename(
            color_code=color.color_code,
            hex_value=color.hex,
        ):
            raise MardCatalogError(
                f"image filename is not deterministic at slot {expected_slot}"
            )
        colors.append(color)

    if len({color.color_code for color in colors}) != EXPECTED_COLOR_COUNT:
        raise MardCatalogError("manifest contains duplicate color codes")
    if len({color.hex for color in colors}) != EXPECTED_COLOR_COUNT:
        raise MardCatalogError("manifest contains duplicate HEX values")
    if len({color.image_filename for color in colors}) != EXPECTED_COLOR_COUNT:
        raise MardCatalogError("manifest contains duplicate image filenames")
    return tuple(colors)


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def build_swatch_png(rgb: tuple[int, int, int]) -> bytes:
    """创建确定性 256×256 RGB PNG，并显式标记 sRGB。"""

    pixel_row = bytes(rgb) * SWATCH_WIDTH
    scanlines = b"".join(b"\x00" + pixel_row for _ in range(SWATCH_HEIGHT))
    header = struct.pack(">IIBBBBB", SWATCH_WIDTH, SWATCH_HEIGHT, 8, 2, 0, 0, 0)
    return b"".join(
        (
            PNG_SIGNATURE,
            _png_chunk(b"IHDR", header),
            _png_chunk(b"sRGB", b"\x00"),
            _png_chunk(b"IDAT", zlib.compress(scanlines, level=9)),
            _png_chunk(b"IEND", b""),
        )
    )

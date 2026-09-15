#!/usr/bin/env python3
"""Fetch and freeze the public MARD 221 CSS color card as a JSON manifest.

The source page does not publish one image per color.  It renders each swatch
from an RGB/HEX value in HTML, so the manifest records those values and a
deterministic filename for a locally generated PNG derivative.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final
from urllib.parse import urlparse

from app.tasks.mard_catalog import (
    EXPECTED_COLOR_COUNT,
    SOURCE_URL,
    SWATCH_HEIGHT,
    SWATCH_WIDTH,
    expected_codes,
    image_filename,
)


MAX_SOURCE_BYTES: Final = 2 * 1024 * 1024
DEFAULT_OUTPUT: Final = Path("app/tasks/manifests/mard_221.json")

_COLOR_CARD_PATTERN = re.compile(
    r'class="color-block"\s+style="background-color:\s*rgb\('
    r"\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\);"
    r'[^>]*>.*?class="color-code"[^>]*>\s*([A-Z]\d{1,2})\s*</span>'
    r'.*?class="color-hex">\s*(#[0-9A-Fa-f]{6})\s*</div>'
    r'.*?class="color-rgb">\s*RGB\('
    r"\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)\s*</div>",
    re.DOTALL,
)


class ManifestSourceError(RuntimeError):
    """Raised when the source page no longer matches the frozen contract."""


@dataclass(frozen=True, slots=True)
class SourceColor:
    """One validated color extracted from the source page."""

    color_code: str
    hex: str
    rgb: tuple[int, int, int]


def extract_colors(source_html: str) -> tuple[SourceColor, ...]:
    """Extract and strictly validate all 221 CSS-rendered color cards."""

    colors: list[SourceColor] = []
    for match in _COLOR_CARD_PATTERN.finditer(source_html):
        block_rgb = tuple(int(match.group(index)) for index in range(1, 4))
        color_code = match.group(4)
        hex_value = match.group(5).upper()
        label_rgb = tuple(int(match.group(index)) for index in range(6, 9))

        if any(channel < 0 or channel > 255 for channel in block_rgb):
            raise ManifestSourceError(f"RGB channel is out of range for {color_code}")
        if block_rgb != label_rgb:
            raise ManifestSourceError(
                f"CSS and displayed RGB values differ for {color_code}"
            )
        derived_hex = "#" + "".join(f"{channel:02X}" for channel in block_rgb)
        if derived_hex != hex_value:
            raise ManifestSourceError(
                f"RGB and displayed HEX values differ for {color_code}"
            )
        colors.append(
            SourceColor(
                color_code=color_code,
                hex=hex_value,
                rgb=block_rgb,
            )
        )

    if len(colors) != EXPECTED_COLOR_COUNT:
        raise ManifestSourceError(
            f"expected {EXPECTED_COLOR_COUNT} colors, found {len(colors)}"
        )
    actual_codes = tuple(color.color_code for color in colors)
    if actual_codes != expected_codes():
        raise ManifestSourceError("color codes or source ordering changed")
    if len(set(actual_codes)) != EXPECTED_COLOR_COUNT:
        raise ManifestSourceError("source contains duplicate color codes")
    if len({color.hex for color in colors}) != EXPECTED_COLOR_COUNT:
        raise ManifestSourceError("source contains duplicate HEX colors")
    return tuple(colors)


def read_source(source_html: Path | None) -> tuple[bytes, str]:
    """Read a supplied snapshot or download the allow-listed public page."""

    if source_html is not None:
        content = source_html.read_bytes()
    else:
        parsed = urlparse(SOURCE_URL)
        if parsed.scheme != "https" or parsed.hostname != "peiseka.com":
            raise ManifestSourceError("source URL is not the allow-listed HTTPS host")
        request = urllib.request.Request(
            SOURCE_URL,
            headers={"User-Agent": "pinkdooHub/0.6 MARD manifest importer"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            final_url = urlparse(response.geturl())
            if final_url.scheme != "https" or final_url.hostname != "peiseka.com":
                raise ManifestSourceError("source redirected outside the allow-listed host")
            content = response.read(MAX_SOURCE_BYTES + 1)
    if not content:
        raise ManifestSourceError("source page is empty")
    if len(content) > MAX_SOURCE_BYTES:
        raise ManifestSourceError("source page exceeds the 2 MiB safety limit")
    try:
        return content, content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ManifestSourceError("source page is not valid UTF-8") from error


def build_manifest(*, source_bytes: bytes, colors: tuple[SourceColor, ...]) -> dict:
    """Build the committed, auditable import manifest."""

    return {
        "schema_version": 1,
        "catalog": "MARD 221 standard colors",
        "source": {
            "url": SOURCE_URL,
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "html_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "representation": "css_rgb_swatch",
            "individual_image_files": False,
        },
        "swatch": {
            "format": "png",
            "width": SWATCH_WIDTH,
            "height": SWATCH_HEIGHT,
            "color_space": "sRGB",
            "representation": "solid_color_generated_from_source_rgb",
        },
        "colors": [
            {
                "slot_no": slot_no,
                "color_code": color.color_code,
                "name": color.color_code,
                "sort": slot_no,
                "is_active": True,
                "hex": color.hex,
                "rgb": list(color.rgb),
                "image_filename": image_filename(
                    color_code=color.color_code,
                    hex_value=color.hex,
                ),
            }
            for slot_no, color in enumerate(colors, start=1)
        ],
    }


def write_manifest(path: Path, manifest: dict, *, replace: bool) -> None:
    """Publish the generated JSON atomically without accidental overwrite."""

    path = path.resolve()
    if path.exists() and not replace:
        raise ManifestSourceError(
            f"manifest already exists: {path}; pass --replace to overwrite"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    ).encode("utf-8")
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch and validate the MARD 221 color-card manifest.",
    )
    parser.add_argument(
        "--source-html",
        type=Path,
        help="Use an already-downloaded UTF-8 HTML snapshot instead of the network.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Manifest path (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the manifest. Without this flag, only validate and preview.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Allow --write to replace an existing manifest.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        source_bytes, source_html = read_source(args.source_html)
        colors = extract_colors(source_html)
        manifest = build_manifest(source_bytes=source_bytes, colors=colors)
        if args.write:
            write_manifest(args.output, manifest, replace=args.replace)
    except (OSError, ManifestSourceError) as error:
        raise SystemExit(f"MARD manifest fetch failed: {error}") from error

    print(f"source={manifest['source']['url']}")
    print(f"source_sha256={manifest['source']['html_sha256']}")
    print(f"colors={len(colors)}")
    print(f"first={colors[0].color_code}:{colors[0].hex}")
    print(f"last={colors[-1].color_code}:{colors[-1].hex}")
    print(f"mode={'write' if args.write else 'preview'}")
    if args.write:
        print(f"output={args.output.resolve()}")
    else:
        print("next=rerun with --write after reviewing the source summary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

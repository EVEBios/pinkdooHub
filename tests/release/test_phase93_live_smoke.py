"""Phase 9.3 HTTPS Smoke 的本地编码安全测试。"""

from scripts.release.phase93_live_smoke import PNG_CONTENT, multipart_image


def test_multipart_image_uses_fixed_safe_filename_and_exact_content() -> None:
    body, content_type = multipart_image({"is_cover": "true", "sort": "0"})

    assert content_type.startswith("multipart/form-data; boundary=phase93-")
    assert b'filename="phase93.png"' in body
    assert b"../" not in body
    assert PNG_CONTENT in body
    assert b"password" not in body.lower()

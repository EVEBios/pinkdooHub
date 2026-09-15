"""API gzip 压缩的端到端边界。"""

import gzip
import json

import pytest
from fastapi import FastAPI, Response
from httpx import AsyncClient
from httpx import ASGITransport

from app.middleware.compression import SelectiveGZipMiddleware


@pytest.mark.asyncio
async def test_large_json_response_is_gzipped_when_client_accepts_it(
    client: AsyncClient,
) -> None:
    async with client.stream(
        "GET",
        "/openapi.json",
        headers={"Accept-Encoding": "gzip"},
    ) as response:
        raw_body = b"".join([chunk async for chunk in response.aiter_raw()])

    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    assert "Accept-Encoding" in response.headers["vary"]
    decoded = gzip.decompress(raw_body)
    assert len(raw_body) < len(decoded)
    assert json.loads(decoded)["openapi"] == "3.1.0"


@pytest.mark.asyncio
async def test_small_json_response_is_not_gzipped(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/health",
        headers={"Accept-Encoding": "gzip"},
    )

    assert response.status_code == 200
    assert "content-encoding" not in response.headers


@pytest.mark.asyncio
async def test_large_json_response_respects_identity_encoding(
    client: AsyncClient,
) -> None:
    response = await client.get(
        "/openapi.json",
        headers={"Accept-Encoding": "identity"},
    )

    assert response.status_code == 200
    assert "content-encoding" not in response.headers


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "accept_encoding",
    ("gzip;q=0", "br, gzip; q=0.000", "gzip;q=NaN", "xgzip"),
)
async def test_large_json_response_respects_explicit_gzip_rejection(
    client: AsyncClient,
    accept_encoding: str,
) -> None:
    response = await client.get(
        "/openapi.json",
        headers={"Accept-Encoding": accept_encoding},
    )

    assert response.status_code == 200
    assert "content-encoding" not in response.headers


@pytest.mark.asyncio
async def test_gzip_content_coding_is_case_insensitive(client: AsyncClient) -> None:
    async with client.stream(
        "GET",
        "/openapi.json",
        headers={"Accept-Encoding": "GZip;Q=0.5"},
    ) as response:
        raw_body = b"".join([chunk async for chunk in response.aiter_raw()])

    assert response.headers["content-encoding"] == "gzip"
    assert json.loads(gzip.decompress(raw_body))["openapi"] == "3.1.0"


@pytest.mark.asyncio
async def test_uploaded_image_namespace_bypasses_gzip() -> None:
    test_app = FastAPI()
    test_app.add_middleware(
        SelectiveGZipMiddleware,
        minimum_size=1024,
        compresslevel=6,
        excluded_path_prefixes=("/uploads/products/",),
    )

    @test_app.get("/uploads/products/sample.webp")
    async def image() -> Response:
        return Response(b"already-compressed" * 200, media_type="image/webp")

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/uploads/products/sample.webp",
            headers={"Accept-Encoding": "gzip"},
        )

    assert response.status_code == 200
    assert "content-encoding" not in response.headers

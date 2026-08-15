# ADR-004：从 FastAPI OpenAPI 生成前端类型

> **Status:** Accepted
> **Date:** 2026-08-15
> **Decision Owners:** pinkdooHub

## Context

现有 FastAPI 路由已经为主要成功/错误信封提供精确 OpenAPI，并能导出 HTTP Bearer Scheme。手工复制 Pydantic DTO 到 TypeScript 容易造成字段、null、Enum、金额和分页漂移。另一方面，通用 OpenAPI Client 往往假设 Fetch/Axios，不适合直接作为 Taro transport。

## Decision

- FastAPI OpenAPI 是前端 API 类型源；
- 使用 `openapi-typescript` 生成 TypeScript 类型；
- 只生成类型，不采用绑定 Fetch/Axios 的生成客户端；
- 项目手写薄 Endpoint API；
- Endpoint 统一调用基于 `Taro.request`/`Taro.uploadFile` 的 Client；
- 生成文件禁止手工编辑；
- CI 检查重新生成后的漂移。

## Rationale

- 保持后端 Schema 与前端静态类型一致；
- 保留 Taro transport、Token、信封和平台上传控制；
- Endpoint 名称可以表达领域用例，而不是泄漏 OpenAPI 生成器细节；
- 便于后端/前端同一 PR 原子变更。

## Important Limit

TypeScript 生成类型不会在运行时验证 JSON。HTTP Client 仍需最低信封 Guard，关键 Storage/路由输入也需显式验证。禁止通过双重断言把未知响应强制变成 DTO。

## Consequences

- 后端 OpenAPI 精度成为前端质量前置条件；
- 导出脚本和生成命令必须可重复；
- API 文档中未来但未实现的接口不会产生类型，前端不得自行补造；
- Schema 变更会在 typecheck 暴露下游影响。

## Validation

- 隔离环境可执行 `app.openapi()`；
- 关键 paths、schemas 和 Bearer Scheme 存在；
- 生成后正式 TypeScript 工程通过 typecheck；
- 重复生成无不稳定 diff；
- Endpoint/API Client 测试覆盖信封和错误。


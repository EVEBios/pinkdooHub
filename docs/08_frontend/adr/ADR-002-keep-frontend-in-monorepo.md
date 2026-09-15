# ADR-002：前端保留在现有 Monorepo

> **Status:** Accepted
> **Date:** 2026-08-15
> **Decision Owners:** pinkdooHub

## Context

当前 GitHub 仓库已经包含 FastAPI 实现、测试、迁移和权威文档。前端与后端共享 OpenAPI、业务规则和发布门槛。需要决定新建独立 GitHub 仓库，还是在当前仓库新增独立项目目录。

## Decision

继续使用现有仓库，在根目录新增：

```text
miniapp/
```

不移动当前 `app/`、`tests/` 和迁移目录，不在 `miniapp/` 内嵌第二个 `.git`。

未来需要复杂桌面管理端时，在同仓库新增：

```text
admin-web/
```

是否拆库届时重新 ADR。

## Rationale

- API 变更可以和后端实现、OpenAPI、前端类型、测试和文档原子 Review；
- 当前由同一项目维护，不需要仓库级权限隔离；
- 后端 Python 与前端 Node 仍可通过目录和 lockfile 独立管理；
- GitHub Actions 可按路径过滤，不要求发布耦合；
- 架构文档有单一权威位置。

## Consequences

- 仓库包含两个运行时和多套工具链；
- 根 README、AI Context 和 CI 必须明确命令作用目录；
- 禁止在根目录混装前端依赖；
- 后端与前端可使用独立版本，但 Tag/发布命名需在发布阶段冻结。

## Split Triggers

出现以下任一实质需求时重新评估：

- 团队和访问权限完全分离；
- 发布、合规或代码所有权要求独立；
- 多个客户端共享独立 SDK，生命周期与服务端显著不同；
- CI 或仓库规模产生已测量的严重负担；
- 前后端开源策略不同。

## Validation

- `miniapp/` 有独立 package/lock/config/test；
- 根 Git 不追踪 `node_modules` 和平台构建产物；
- CI 能按路径运行，并在 API 变化时同时触发；
- Python 完整测试不依赖安装 Node，前端静态测试不依赖运行数据库。


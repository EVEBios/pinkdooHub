# pinkdooHub

pinkdooHub 是一个面向拼豆门店的后端管理系统，基于 FastAPI、Tortoise ORM、Pydantic 和 Redis 构建。开发环境使用 SQLite，生产数据库设计面向 MySQL 8+。

当前代码版本候选为 **v0.5.0（尚未发布）**。Phase 4.1 Product Module 与 Phase 4.2 Order Module 均已完成实现和最终 Review；下一业务阶段为 Phase 4.3 Inventory。

## 当前能力

- 用户注册、登录、Token 刷新与登出，以及个人资料和密码修改。
- RBAC 权限链、管理员用户列表和禁用操作。
- 敏感操作顺序审计，以及 Product 操作历史分页查询。
- Product、ExperienceOption、ProductKit 和 ProductImage 的完整业务、持久化与 API 链路。
- 22 个 Product API 操作，包括公开查询、ADMIN+ 管理、图片上传和审计历史。
- Product 图片大小、格式、MIME 和安全路径校验，以及上传失败补偿和延迟物理清理。
- Order v1.0 的 Experience 下单、不可变 Product/Option/价格快照、用户/管理查询、取消、人工确认支付、完成和审计历史。
- Order 状态与审计原子事务、订单号冲突重试、分页组合筛选、用户资源隐藏和完整 HTTP 错误/边界矩阵。
- 统一成功/错误响应、全局异常处理和精确 OpenAPI 响应契约。

当前完整测试套件包含 **1178 项测试**。详细版本记录见 [Development Changelog](docs/05_development/changelog.md)。

## 技术栈

| 领域 | 组件 |
|---|---|
| Web | FastAPI 0.139.2、Uvicorn 0.51.0 |
| ORM / Migration | Tortoise ORM 1.1.7、Aerich 0.9.3 |
| Database | SQLite（开发/测试）、MySQL 8+（生产设计） |
| Schema / Config | Pydantic 2.13.4、pydantic-settings 2.14.2 |
| Cache / Token State | Redis 8.0.1 |
| Testing | pytest 9.1.1、pytest-asyncio、HTTPX、fakeredis |

精确依赖版本以 [requirements.txt](requirements.txt) 为准，测试配置以 [pyproject.toml](pyproject.toml) 为准。

## 快速开始

### 1. 创建虚拟环境并安装依赖

Windows PowerShell：

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

macOS / Linux：

```bash
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

项目当前以 Python 3.10 兼容性为基线。不要提交 `.venv`、缓存目录或本地运行文件。

### 2. 创建本地配置

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

macOS / Linux：

```bash
cp .env.example .env
```

开发环境默认使用 SQLite。启动前至少检查：

- `APP_ENV=development`
- `DB_ENGINE=sqlite`
- `REDIS_URL` 指向可用 Redis
- `JWT_SECRET_KEY` 仅可在本地开发使用示例值；生产必须设置安全随机密钥
- `PRODUCT_IMAGE_UPLOAD_DIR` 和 `PRODUCT_IMAGE_BASE_URL` 符合本地存储规划

`.env` 已被 Git 忽略，不得将密码、Token、私钥或真实连接串提交到仓库。

### 3. 启动基础设施和应用

先确保 Redis 可访问，再启动开发服务：

```bash
uvicorn app.main:app --reload
```

默认入口：

- API 根地址：`http://127.0.0.1:8000/`
- Swagger UI：`http://127.0.0.1:8000/docs`
- ReDoc：`http://127.0.0.1:8000/redoc`
- OpenAPI JSON：`http://127.0.0.1:8000/openapi.json`
- 健康检查：`http://127.0.0.1:8000/api/v1/health`

所有业务 API 使用 `/api/v1` 前缀。`v1` 只属于 HTTP 传输层版本，不需要复制到 Schema、Service、Repository 或 Model 目录。

## 测试与检查

运行完整测试：

```bash
python -m pytest tests/ -q
```

提交前至少执行：

```bash
python -m pytest tests/ -q
python -m compileall -q app tests
python -m pip check
git diff --check
```

Product、Order 或持久化相关改动还应运行对应专项测试，并对照 [Code Review Checklist](docs/07_process/code_review_checklist.md) 检查架构、安全、事务、性能、测试和文档联动。

## 架构边界

核心调用链：

```text
API → Service → Repository → Model → MySQL / SQLite
          │
          ├─→ Validator
          └─→ Redis / shared infrastructure
```

- API：协议适配、输入校验、认证/权限依赖、Mapper 和统一成功响应。
- Service：业务规则、事务边界、Repository 协调和审计编排。
- Validator：关键状态变迁前的同步纯业务校验，不查库、不写库。
- Repository：Tortoise ORM 查询和原子 CRUD，不包含业务判断。
- Model：表结构、关系、约束和索引声明。
- Schema：请求与响应数据形状，不依赖 Model、Repository 或 Service。

禁止 API 直接访问 Repository/Model，禁止 Service 直接操作 Model，禁止 Repository 反向依赖 Service。完整约束见 [Architecture](docs/04_architecture/architecture.md) 和 [Coding Standards](docs/05_development/coding_standards.md)。

## Product 图片清理

ProductImage 的 HTTP 删除是逻辑删除，物理文件由独立运维命令延迟清理。命令默认仅预览候选：

```bash
python -m app.tasks.product_image_cleanup \
  --before 2026-08-01T00:00:00+08:00 \
  --batch-size 100
```

确认截止时间、候选对象和存储目录后，才可使用相同参数增加 `--apply`：

```bash
python -m app.tasks.product_image_cleanup \
  --before 2026-08-01T00:00:00+08:00 \
  --batch-size 100 \
  --apply
```

不要在 Web 启动流程、数据库事务或未确认保留策略时自动执行物理清理。命令只处理当前存储命名空间中的安全 UUID 文件，并保护仍被有效记录引用的 URL。

## 数据库迁移

MySQL 是生产迁移的权威方言，SQLite 只用于本地开发与自动化测试。当前 MySQL 8+ 首迁移和 Order 增量迁移均已离线生成并通过静态契约测试，但尚未应用到任何 MySQL 数据库。

生产环境禁止通过应用启动自动建表。执行 `aerich upgrade` 前必须：

1. 明确目标环境、MySQL 实例和版本；
2. 完成只读 Schema 审计；
3. 创建可验证备份或快照；
4. 先在临时或预发布 MySQL 执行并验证；
5. 获得明确执行授权并准备回滚方案。

禁止为了对齐版本记录而未经审计使用 `--fake`。完整流程见 [Database Migration Workflow](docs/07_process/database_migration_workflow.md)。

## 文档导航

| 主题 | 文档 |
|---|---|
| Product 权威业务规则 | [Product Business Rules](docs/01_requirements/product_business_rules.md) |
| Product API v1.0 | [Product API](docs/03_api/product_api.md) |
| Order 业务规则 | [Order Module](docs/01_requirements/order_module.md) |
| Order API v1.0 | [Order API](docs/03_api/order_api.md) |
| 通用 API 约定 | [API Design Conventions](docs/03_api/api_design_conventions.md) |
| 数据库设计 | [Database Design](docs/02_database/database_design.md) |
| 分层与目录 | [Architecture](docs/04_architecture/architecture.md) |
| 编码与 Git 规范 | [Coding Standards](docs/05_development/coding_standards.md) |
| AI/开发上下文 | [AI Context](docs/06_ai/AI_CONTEXT.md) |
| 迁移流程 | [Database Migration Workflow](docs/07_process/database_migration_workflow.md) |

业务行为以 `docs/01_requirements/` 为准，HTTP 契约以 `docs/03_api/` 为准，表结构与索引以数据库设计和 DBML 为准；当前是否已实现必须结合代码、测试与 changelog 判断。

## Git 工作流

- `main`：生产就绪代码，只接受 Pull Request，禁止直接 push。
- `develop`：开发集成分支，是 feature/fix 分支的合入目标。
- `feature/<name>`：从 `develop` 创建的新功能分支。
- `fix/<name>`：Bug 修复分支。

提交信息使用 Conventional Commits：

```text
<type>(<scope>): <English imperative subject>
```

示例：

```text
feat(product): add product audit history
fix(auth): reject revoked refresh token
docs(readme): document local development workflow
```

一个提交只包含一个逻辑单元。未经明确授权不得执行数据库迁移、创建 tag、发布 Release、force push 或直接向受保护分支推送。

## 当前限制与下一阶段

- v0.5.0 仍是未发布候选版本，尚未创建 Git tag 或 GitHub Release。
- MySQL 首迁移与 Order 增量迁移均尚未应用；部署必须遵循迁移流程。
- refresh token 尚未轮换；登录/注册尚未限流。
- 邮件验证、OAuth、管理员启用用户和头像上传尚未实现。
- Phase 4.3 将引入库存流水、自动扣减/恢复和并发库存控制；当前 Order 明确拒绝 Kit 下单。

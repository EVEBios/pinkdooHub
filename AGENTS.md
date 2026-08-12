# pinkdooHub 项目指令

本文件是 Codex 在本仓库中的项目级开发规则。它补充 `~/.codex/AGENTS.md` 的全局规则，并以本项目的架构、当前阶段和文档体系为准。详细设计保存在 `docs/`；本文件只保留每次任务都需要知道的约束和导航。

## 项目概览

pinkdooHub 是拼豆店管理系统，后端技术栈为 FastAPI、Tortoise ORM、Pydantic、Redis，以及 MySQL（生产）/ SQLite（开发）。依赖版本以 `requirements.txt` 为准，测试配置以 `pyproject.toml` 为准。

主要技术组件：

- FastAPI 0.139.2 + Uvicorn 0.51.0
- Tortoise ORM 1.1.7 + Aerich 0.9.3
- asyncmy 0.2.11（MySQL 异步驱动）
- Pydantic 2.13.4 + pydantic-settings 2.14.2
- Redis 8.0.1
- pytest 9.1.1 + pytest-asyncio + httpx

## 当前 Phase 与范围

当前基线为 **v0.3.0**，正在进入 **Phase 4.1：Product Module 实现阶段**。

已完成：

- 项目基础设施、统一响应、全局异常处理、配置、日志、数据库和 Redis 接入。
- 用户注册、登录、Token 刷新/登出、个人资料和密码修改。
- RBAC 权限链、管理员用户列表与禁用操作。
- 敏感操作的顺序审计日志。
- Product 业务规则、数据模型和 API 设计。

当前实现状态：

- Product 的业务、数据库、API 和 Schema 契约已完成；`app/common/` 中的 Product Enum/常量、`app/schemas/product*.py`、四个 Product Model，以及 `app/repositories/product_repo.py` 已实现并有契约测试。Product Validator 阶段已完成。Product Service 的上架/下架状态流转已实现：前置资源与状态冲突、进入 Online 前 Validator、状态更新与对应审计同事务提交均有专项测试。其余 Product Service 用例和 API 仍待实现，当前端点不可调用。
- MySQL 8+ 权威首迁移已离线生成、通过静态契约测试并提交，但尚未应用到任何 MySQL 数据库。SQLite 开发库已在可恢复备份后从当前 Tortoise Models 重建；未应用 MySQL 迁移，也未 fake Aerich 版本。
- ExperienceOption 配置组合在全历史范围内唯一；再次创建相同已删除组合时恢复原 Option ID、更新当前价格并保留图片关联，不创建第二条版本记录。
- Phase 4.1 的 Kit 库存采用直接设置最终值模式；库存流水、自动扣减/恢复和并发控制仍属于 Phase 4.3 Inventory。
- 架构文档中出现的 Product、Order、Inventory 文件可能是规划结构，不代表代码已经存在；开始任务前必须检查实际文件树和测试。
- Product API 文档当前仍标记为 Draft。实现时以 `product_business_rules.md` 和 `product_api.md` 为契约；遇到缺口或冲突先指出，不自行发明业务规则。

后续阶段：

- Phase 4.2：Order。
- Phase 4.3：Inventory；库存流水/调整模型属于该阶段。
- 未经当前任务明确要求，不提前实现后续 Phase，不把未来设计误报为已完成能力。

当前已知限制包括 refresh token 未轮换、登录/注册未限流、未实现邮件验证和 OAuth、管理员启用用户及头像上传仍待实现。不要在无关任务中顺手扩展这些范围。

## 文档导航与事实来源

遇到细节时先读对应文档，不凭记忆猜测。`docs/` 中既有已实现说明，也有未来设计；必须结合“当前 Phase”和实际代码判断实现状态。

### 开发与架构

| 需要了解 | 文档 |
|----------|------|
| AI/开发全局上下文、文档联动和流程 | [`docs/06_ai/AI_CONTEXT.md`](docs/06_ai/AI_CONTEXT.md) |
| 分层、目录、依赖方向、请求流程、基础组件 | [`docs/04_architecture/architecture.md`](docs/04_architecture/architecture.md) |
| 代码、类型、各层、性能、测试和 Git 规范 | [`docs/05_development/coding_standards.md`](docs/05_development/coding_standards.md) |
| 已完成能力、重要决策和已知限制 | [`docs/05_development/changelog.md`](docs/05_development/changelog.md) |
| 完成功能后的检查项目 | [`docs/07_process/code_review_checklist.md`](docs/07_process/code_review_checklist.md) |
| 数据库迁移生成、Review、执行与既有库基线 | [`docs/07_process/database_migration_workflow.md`](docs/07_process/database_migration_workflow.md) |
| 用户模块历史摘要 | [`docs/06_ai/User_Module_Summary.md`](docs/06_ai/User_Module_Summary.md) |

### 需求与业务规则

| 模块 | 文档 |
|------|------|
| 用户需求 | [`docs/01_requirements/user_module.md`](docs/01_requirements/user_module.md) |
| Product 需求概要 | [`docs/01_requirements/product_module.md`](docs/01_requirements/product_module.md) |
| Product 权威业务规则 | [`docs/01_requirements/product_business_rules.md`](docs/01_requirements/product_business_rules.md) |
| Order 需求 | [`docs/01_requirements/order_module.md`](docs/01_requirements/order_module.md) |

### API 与数据

| 需要了解 | 文档 |
|----------|------|
| 通用响应、分页、错误码和 Enum 约定 | [`docs/03_api/api_design_conventions.md`](docs/03_api/api_design_conventions.md) |
| 用户 API | [`docs/03_api/user_api.md`](docs/03_api/user_api.md) |
| Product API | [`docs/03_api/product_api.md`](docs/03_api/product_api.md) |
| Order API | [`docs/03_api/order_api.md`](docs/03_api/order_api.md) |
| 表、字段、约束和索引 | [`docs/02_database/database_design.md`](docs/02_database/database_design.md) |
| 可维护的 ER 源文件 | [`docs/02_database/er_diagram.dbml`](docs/02_database/er_diagram.dbml) |

按主题确定事实来源：

- 业务行为以对应的 `docs/01_requirements/` 文档为准。
- HTTP 契约以对应的 `docs/03_api/` 文档为准。
- 表结构和索引以 `database_design.md` 与 `er_diagram.dbml` 为准，两者必须保持一致。
- 当前是否已经实现，以实际代码、测试和 changelog 共同判断；规划目录或 Draft 文档不能当成实现证据。
- 架构边界和编码方式以本文件、`architecture.md` 和 `coding_standards.md` 为准。
- 文档相互冲突时不要静默选择其中一份：检查代码、测试、文档版本和当前 Phase，明确报告差异后再按任务范围处理。

## 项目架构

核心调用链为：

```text
API → Service → Repository → Model → MySQL/SQLite
          │
          ├─→ Validator（关键状态变迁前的纯业务校验）
          └─→ core/Redis/共享基础设施
```

各层职责：

- `app/api/`：路由、请求参数、Pydantic 校验、认证/权限依赖、调用 Service、构造统一成功响应；不得写业务逻辑或数据库查询。
- `app/services/`：业务规则和编排、权限判断、事务边界、Repository 协调、Validator 调用、外部基础设施调用。
- `app/validators/`：关键状态变迁前的完整性判断；数据由 Service 准备，只判断并抛业务异常，不查库、不写库、不返回 bool。
- `app/repositories/`：Tortoise ORM 查询和原子 CRUD；不得包含状态判断、权限判断或业务异常。
- `app/models/`：表结构、关系、字段约束和索引声明；不得包含应用层业务行为。
- `app/schemas/`：请求和响应数据形状；可依赖 `common/`，不得依赖 Model、Repository 或 Service。
- `app/common/`：跨领域 Enum、常量、分页和响应类型，不反向依赖应用层。
- `app/core/`：配置、安全、Redis 和基础异常，不反向依赖业务层。
- `app/middleware/`：HTTP 横切能力和统一异常处理。
- `app/utils/`：无状态纯工具，不依赖应用层。

依赖规则：

- 禁止 API 直接调用 Repository 或 Model。
- 禁止 Service 直接操作 Model；所有持久化经过 Repository。
- 禁止普通业务 Service 调用另一个业务 Service；跨领域数据通过对应 Repository 获取。
- `AuditLogService` 是当前明确的共享基础设施 Service 例外，可以被业务 Service 调用。新增例外必须先在架构文档中说明共享属性和依赖方向。
- 禁止 Repository 调用 Service、Validator 或 Redis。
- 禁止 Validator 调用 Service 或 Repository。
- 每增加一个 import，都检查是否发生反向依赖或跳层调用。

## 强制开发规则

### 异常与响应

- 业务错误由 Service 或 Validator 抛出，禁止使用 FastAPI `HTTPException` 表达业务规则。
- 已有模块命名异常时优先使用，例如 `UsernameAlreadyExists()`、`UserNotFound()`；稳定的新业务错误应在模块异常文件中定义命名异常并继承 `BusinessException`。一次性且没有命名类型的错误才直接构造 `BusinessException(code=..., message=...)`。
- 异常由 `app/middleware/exception.py` 统一转换；API 不用 `try/except` 手写错误响应。
- 成功响应统一使用 `success(data=..., message=...)`，禁止手写 `{"code": 0, ...}`、返回其他信封或返回裸列表。
- API 输出必须先经 Pydantic Out Schema 验证/序列化，例如 `UserOut.model_validate(obj).model_dump()`，再传给 `success()`；禁止直接返回 ORM Model。
- 任何响应、日志和调试信息都不得包含 `password`、Token、密钥等敏感字段。

### 命名、类型与数据模型

- 类名使用 PascalCase；函数、变量和文件使用 snake_case；常量使用 SNAKE_CASE。
- Schema 使用明确后缀，如 `XxxCreate`、`XxxUpdate`、`XxxOut`、`XxxListItem`、`XxxRequest`。
- 公开函数和各层方法必须标注参数及返回类型；Out Schema 配置 `from_attributes = True`。
- 禁止 Magic Number；稳定业务值放入 `app/common/constants/`，枚举放入 `app/common/enums/`。
- Enum 的数据库表示按模块权威设计执行：User 当前使用 `SmallIntField` + `IntEnum`；Product 的 `ProductType`/`ProductStatus` 设计为字符串 Enum。不要把一种存储方式机械套到所有模块。
- 金额使用 `Decimal`/`DecimalField(max_digits=10, decimal_places=2)`，禁止使用 float。
- 列表和分页接口使用 `Page[T]`，不得用裸 tuple 表达分页结果，也不得无限制全表加载。

### 数据、事务与性能

- 跨表写入或必须保持原子性的操作使用 `in_transaction()`。
- 禁止在 `for` 循环中逐条 `await` 查询；按关系使用 `select_related()` 或 `prefetch_related()`。
- 批量写入或更新优先使用 `bulk_create()`、`bulk_update()` 或集合更新，避免循环单条保存。
- 列表查询必须包含分页 `limit`/`offset`；只读取需要的字段。
- 索引根据实际查询模式设计，通过 Model `Meta.indexes` 集中声明，并同步数据库文档和 ER 图。
- Product 上架等关键状态变迁必须调用对应 Validator；Validator 失败时直接抛异常。

### 日志

- 每个模块使用 `logging.getLogger(__name__)`，禁止 `print()` 和遗留调试输出。
- 关键业务操作记录必要上下文；异常记录应支持定位问题，适用时使用 `exc_info=True`。
- 不在日志中记录密码、Token 或完整敏感个人信息。

## 开发流程

开始任务时：

1. 确认任务所属模块、当前 Phase 和明确范围。
2. 先读该模块的需求文档与 API 文档；Product 任务必须同时读 `product_business_rules.md` 和 `product_api.md`。
3. 涉及表结构时再读 `database_design.md` 和 `er_diagram.dbml`；涉及分层或新增目录时读 `architecture.md`；涉及具体写法时读 `coding_standards.md`。
4. 检查实际代码和测试，不根据规划文档假设文件、端点或能力已经存在。

实现与验证时：

1. 按当前架构做完成任务所需的最小改动。
2. 同步新增或更新正常、异常、权限和关键边界测试。
3. 运行与改动直接相关的测试，再运行完整测试：`pytest tests/ -q`。
4. 检查分层、依赖方向、事务、安全、性能和敏感数据处理。
5. 按下方联动表检查并更新文档；文档与代码属于同一逻辑改动。
6. 完成一个独立功能模块时更新 `docs/05_development/changelog.md`。
7. 使用 `git diff` 和仓库状态复核变更范围，确认没有无关文件、调试输出、敏感信息或意外生成物。
8. 只有用户明确要求时才 commit、push、发布、打 tag 或执行数据库迁移；完成实现不自动扩大为远端或环境变更授权。

无法运行测试或检查时，明确列出未验证项和原因，不得声称已经通过。

## 文档更新联动

| 代码或设计变化 | 必须检查/更新 |
|----------------|---------------|
| Model、表、字段、约束或索引 | `docs/02_database/database_design.md` + `docs/02_database/er_diagram.dbml` |
| API 端点、请求、响应或错误 | `docs/03_api/<module>_api.md` |
| Enum 或映射方式 | `docs/03_api/api_design_conventions.md` 对应章节 + `docs/06_ai/AI_CONTEXT.md` 速查表 |
| 业务规则、状态流或权限 | `docs/01_requirements/<module>.md`；Product 还要检查 `product_business_rules.md` |
| 目录、分层或依赖方向 | `docs/04_architecture/architecture.md` |
| 依赖或技术栈 | `requirements.txt` + `architecture.md` 技术栈章节 |
| 通用编码或流程规范 | `docs/05_development/coding_standards.md`；必要时同步本文件 |
| 新错误码 | 模块 API 文档 + `api_design_conventions.md` + `AI_CONTEXT.md` 错误码速查 |
| 独立功能模块完成 | `docs/05_development/changelog.md` |

更新文档时说明设计原因和取舍，保持示例与实际代码一致，并沿用同目录现有格式。不要只写“详见代码”，也不要在多个文档复制一份可能失同步的规则。

## 完成与 Review

完成较大任务或独立功能模块后，对照 `docs/07_process/code_review_checklist.md` 检查：

- Architecture：分层、依赖方向、文件归属。
- Security：密码、密钥、Token、权限、输入和 SQL 安全。
- Naming & Types：命名、类型标注、Schema、Enum、常量。
- Exception & Response：命名业务异常、统一中间件、`success()` 和 Pydantic 输出。
- Database & Performance：字段、约束、索引、事务、分页和 N+1。
- Testing & Logging：新增测试、异常/边界覆盖、日志和调试输出。
- Documentation：API、需求、数据库、架构、AI context 和 changelog 联动。

最终交付说明至少包含：修改内容、运行过的测试及结果、文档影响、是否需要数据库迁移/版本升级/新增依赖，以及仍未完成或未验证的事项。

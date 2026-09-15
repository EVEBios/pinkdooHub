# pinkdooHub 项目指令

本文件只保留每次在仓库工作都需要的边界、开发约定和文档导航；全局通用规则见 `~/.codex/AGENTS.md`。具体业务、API、迁移和发布事实以对应权威文档及实际代码/测试为准，不从历史摘要推断当前环境状态。

> 当前 Gate A 的迁移/发布事实以[M15 完成报告](docs/09_release/reports/gatea_m15_completion_2026-09-16.md)和现场原始记录为准：截至 2026-09-16，M15 已 finalized。较早 A–G 恢复摘要属于历史，不能替代现场证据；微信公开发布仍需独立门槛。

## 项目与当前边界

pinkdooHub 是拼豆店管理系统。后端使用 FastAPI、Tortoise ORM、Pydantic、Redis、MySQL（生产）/SQLite（开发）；前端为 Taro 小程序。精确依赖版本以 `requirements.txt`、`miniapp/package.json` 和锁文件为准，测试配置以 `pyproject.toml` 为准。

- 当前代码为尚未发布的 v0.6.0 候选。Product、Order、Inventory、Wallet/Payment/Refund v1、Reservation N1、M6 自选颜色 Kit、M7 固定店休、M8 HEX 色块与 M9 二维码开台均已完成仓库实现；仓库实现、隔离测试和本地数据不能当作任何持久环境已迁移或可发布的证据。
- **历史检查点（2026-09-13，已由上方完成报告更新）：** 当时 Gate A 为 **No-Go**：live 配置、数据库与五服务是旧候选 A/M9，但 `current` 和最后 finalized lineage 仍是 S/M7；A 验收失败的 pending 与 B 停在 `prepared` 的 retirement pending 必须保留。C 虽有远端 9/9，真实 stage 在写入前失败，不能复用。后续 D 的前滚、验收、恢复与收口必须以 [Release README](docs/09_release/README.md)、[Go/No-Go Checklist](docs/09_release/go_no_go_checklist.md) 和现场 Release Record 的最新状态为准；本段摘要不授权任何环境操作。
- 不得手工删除或修改受保护 pending、拼接旧证据、重跑 M7→M9、降级当前数据库、临时注入 Secret，或将 Gate A 证据外推到共享、预发布或生产环境。真实微信支付/充值/退款、正式微信小程序码、上传/灰度/发布与持久数据库迁移均需各自明确授权。
- 开始相关任务时检查实际文件树、测试、迁移链和现场证据；规划文档、旧测试数字及已完成阶段的目录图不等于当前能力或环境事实。

## 文档导航与事实来源

按任务主题读取，不要求每次通读所有文档：

| 主题 | 权威入口 |
|------|----------|
| 业务规则 | [`docs/01_requirements/`](docs/01_requirements/) 对应模块；Product 以 [product_business_rules.md](docs/01_requirements/product_business_rules.md) 为准 |
| HTTP 契约、错误码 | [`docs/03_api/`](docs/03_api/) 对应模块及 [api_design_conventions.md](docs/03_api/api_design_conventions.md) |
| 表、字段、索引 | [database_design.md](docs/02_database/database_design.md) 与 [er_diagram.dbml](docs/02_database/er_diagram.dbml)，两者保持一致 |
| 分层与编码 | [architecture.md](docs/04_architecture/architecture.md)、[coding_standards.md](docs/05_development/coding_standards.md) |
| 已完成能力与历史 | 实际代码/测试、[changelog.md](docs/05_development/changelog.md)；按需查 [AI_CONTEXT.md](docs/06_ai/AI_CONTEXT.md) 索引 |
| 迁移与发布 | [database_migration_workflow.md](docs/07_process/database_migration_workflow.md)、[Release README](docs/09_release/README.md)、[Go/No-Go Checklist](docs/09_release/go_no_go_checklist.md) |
| 前端 | [frontend_architecture.md](docs/08_frontend/frontend_architecture.md)、[api_integration_contract.md](docs/08_frontend/api_integration_contract.md)、[testing_strategy.md](docs/08_frontend/testing_strategy.md) |
| Review | [code_review_checklist.md](docs/07_process/code_review_checklist.md) |

文档冲突时，不静默选择：核对代码、测试、文档版本和当前 Phase，说明差异后按本次任务范围处理。不得把 Draft、历史报告或旧 Release Record 视为新环境的通过证据。

## 架构与实现约定

主要调用链为 `API → Service → Repository → Model`。`app/api/` 负责协议、输入校验、认证授权和统一响应；`app/services/` 负责业务规则、事务与编排；`app/repositories/` 负责 ORM 查询和持久化；`app/models/` 声明结构与索引；`app/schemas/` 定义请求/响应形状；`app/validators/` 在关键状态变迁前做纯业务校验，不查库或写库。`app/common/`、`app/core/`、`app/middleware/` 和 `app/utils/` 不反向依赖具体业务层。

- API 不直接访问 Repository/Model，不在路由中写业务规则；Service 不直接操作 Model，持久化经过 Repository。Repository 不调用 Service/Validator，也不判定业务权限或抛业务异常。Validator 由 Service 准备数据，只判断并抛业务异常。
- 普通业务 Service 不直接调用另一业务 Service；跨领域数据通过对应 Repository 协作。既有共享 `AuditLogService` 是明确例外；新增例外先核对架构文档与依赖方向。
- 业务错误使用既有或新定义的命名异常，由 `app/middleware/exception.py` 统一转换；不以 FastAPI `HTTPException` 承载业务错误，也不按错误码号段猜 HTTP 状态。成功输出用 `success()`；先经 Pydantic Out Schema 验证/序列化，不直接返回 ORM 对象或敏感字段。
- 金额使用 `Decimal`，不用 `float`；Enum 的数据库和 API 表示按模块权威契约处理，不把 User 的整数状态机械套到 Product/Order。稳定业务值放入 `app/common/constants/` 或 `app/common/enums/`，不要散落 Magic Number。
- 跨表原子操作由 Service 明确持有事务；按业务既定锁序和幂等规则处理并发。列表必须分页并稳定排序；批量读取或预加载关系，避免循环查询和 N+1。Model 索引与数据库文档、ER 图同步。
- 公开接口按项目风格标注类型。日志使用模块 logger，不遗留 `print()`，不输出密码、Token、密钥或完整敏感个人信息；错误保留定位上下文但不泄密。

## 开发与交付流程

1. 确定模块和范围，读对应需求/API；Product 任务同时读权威业务规则。涉及结构、跨层或发布时再读数据库、架构或发布文档。
2. 修改前查实际代码、测试、配置和仓库状态。只做当前任务所需改动，保留用户已有未提交修改；涉及公共契约或持久数据时先评估兼容、迁移和回滚。
3. 行为变更补正常、失败、权限和关键边界测试。先运行定向测试，再按风险运行相关静态检查及完整套件 `pytest tests/ -q`；无法运行时准确说明未验证项。
4. 检查文档联动：业务规则→对应需求文档；端点/错误→对应 API 文档及通用约定；表/索引→数据库设计和 DBML；分层→架构文档；依赖→清单、锁文件及相关架构说明；独立功能完成→changelog。不要维护第二份会漂移的 Enum/错误码速查表。
5. 完成前对照 [Review Checklist](docs/07_process/code_review_checklist.md)，检查安全、事务、性能、类型、测试、文档及 `git diff`/仓库状态。仅在用户明确要求时 commit、push、发布、打 tag 或执行持久数据库迁移。

最终说明改动、验证结果、文档影响、迁移/版本/依赖需求和未完成事项；任务资源按全局规则精确回收并复核。

# AI Context — pinkdooHub

本页是**按需查阅的文档索引和边界提示**，不是第二份 `AGENTS.md`，也不记录逐次 CI、候选 SHA 或发布操作日志。每次任务默认遵循项目根目录 [AGENTS.md](../../AGENTS.md)；只读取与任务相关的下列权威文档。文档和现状不一致时，先核对实际代码、测试、迁移与对应环境的 Release Record。

## 从哪里找事实

| 任务 | 先读 |
|------|------|
| 通用架构、编码和 Review | [architecture.md](../04_architecture/architecture.md)、[coding_standards.md](../05_development/coding_standards.md)、[code_review_checklist.md](../07_process/code_review_checklist.md) |
| 用户与认证 | [user_module.md](../01_requirements/user_module.md)、[user_api.md](../03_api/user_api.md) |
| Product / 颜色 Kit / 图片 | [product_business_rules.md](../01_requirements/product_business_rules.md)、[product_api.md](../03_api/product_api.md) |
| Order / Inventory | [order_module.md](../01_requirements/order_module.md)、[order_api.md](../03_api/order_api.md)、[inventory_module.md](../01_requirements/inventory_module.md)、[inventory_api.md](../03_api/inventory_api.md) |
| Wallet / Payment / Refund | [wallet_module.md](../01_requirements/wallet_module.md)、[wallet_api.md](../03_api/wallet_api.md) |
| Reservation N1 与 N2 规划 | [reservation_module.md](../01_requirements/reservation_module.md)、[reservation_api.md](../03_api/reservation_api.md)、[N2 notification plan](../01_requirements/reservation_wechat_notification_plan.md) |
| 首页待办、结果已读与跨模块通知规划 | [首页提醒整体规划与执行记录](../01_requirements/home_attention_notification_plan.md)；[已实现预约提醒需求](../01_requirements/attention_module.md)；[提醒 API](../03_api/attention_api.md)；微信店休投递边界仍见原 N2 规划 |
| M9 桌台 | [table_session_module.md](../01_requirements/table_session_module.md)、[table_session_api.md](../03_api/table_session_api.md) |
| 通用响应、Enum、错误码 | [api_design_conventions.md](../03_api/api_design_conventions.md) 与 `app/common/` 实际定义；不要从历史速查表推断 |
| 表结构、迁移 | [database_design.md](../02_database/database_design.md)、[er_diagram.dbml](../02_database/er_diagram.dbml)、[database_migration_workflow.md](../07_process/database_migration_workflow.md) |
| 前端架构、多端、集成与测试 | [frontend_architecture.md](../08_frontend/frontend_architecture.md)、[multi_platform_strategy.md](../08_frontend/multi_platform_strategy.md)、[api_integration_contract.md](../08_frontend/api_integration_contract.md)、[testing_strategy.md](../08_frontend/testing_strategy.md) |
| 顾客根页与视觉约定 | [PRODUCT.md](../../PRODUCT.md)、[DESIGN.md](../../DESIGN.md)、[Surface Brief](../../.impeccable/surfaces/miniapp-customer-root-tabs.md) |
| 微信发布及 Gate A/B | [Release README](../09_release/README.md)、[Go/No-Go Checklist](../09_release/go_no_go_checklist.md)、[Release Decision Record](../09_release/release_decision_record.md)、[release_drill_runbook.md](../09_release/release_drill_runbook.md) |
| 已完成工作及历史测试结果 | [changelog.md](../05_development/changelog.md)、[release reports](../09_release/reports/)；具体能力再以代码和测试核验 |

精确依赖版本查 `requirements.txt`、`miniapp/package.json` 和锁文件；不要在本页复制版本表。需要了解某一模块时只读对应行的文档，不必顺序加载整个 `docs/`。

## 容易误判的边界

- **实现状态与环境状态分开。** v0.6.0 仍是未发布候选；Product、Order、Inventory、Wallet/Payment/Refund v1、Reservation N1、M6/M7/M8/M9 已完成仓库实现，不代表共享、预发布或生产数据库已迁移。Gate A 的当前 No-Go 和受保护恢复链以 [Release README](../09_release/README.md) 与该环境的最新 Release Record 为准，不以本页的历史日期或本地测试数字推断。
- **M9 不是微信支付或通知项目。** 桌台占用、计时、普通占位二维码已实现；微信官方小程序码和真实微信支付仍 Deferred。Reservation N1 独立于 Order/Payment，N2 主动通知、durable outbox 和 worker 仍是后续范围；页面显示状态不等于主动通知。
- **库存和资金按各自权威流水处理。** Kit 库存不再通过 Product 的直接设置入口修改；创建 Pending Kit/混合订单扣减，Pending 取消恢复，PAID 退款是否恢复按相应契约。钱包/支付/退款的内部演练能力不等于真实 Provider 可用；生产开关和真实资金操作需单独授权。调整、支付、退款及桌台事件的事务、锁序和幂等细节查对应需求与 API 文档。
- **前端能力需区分平台和验收层级。** 仓库测试、四端构建、微信开发者工具 Functional、iOS/Android 真机、真实 Origin/HTTPS RC、官方小程序码及发布是不同证据；不要用其中一项替代另一项。前端当前页面与路由以 `miniapp/` 实际代码和测试为准。
- **历史说明不是待办指令。** 旧 Phase 的实现步骤、故障诊断、快照数字和已修复 TODO 留在 changelog、发布记录或 Git 历史中。遇到本页与代码或权威契约冲突，报告差异并按本次任务范围修正，不能照旧叙述执行。

## 文档维护

文档与代码同属一个逻辑改动。变更业务规则、API、数据库结构、Enum/错误码、前端平台行为或开发流程时，按项目 [AGENTS.md 的文档联动规则](../../AGENTS.md#开发与交付流程) 更新对应**权威文档**；独立功能完成时更新 [changelog.md](../05_development/changelog.md)。本页只在索引、事实来源优先级或跨模块边界变化时更新，不再逐次追加测试计数、发布检查点或第二份模块契约。

完成前运行与改动相关的测试和检查、复核差异，并按 [Review Checklist](../07_process/code_review_checklist.md) 检查。仅在用户明确要求时提交、推送、迁移或发布；不要把旧文档的“Code + Test + Documentation + Commit”当成自动提交授权。


2026-09-14：站内提醒已扩展至 P1.2 订单/桌台（M13，目标环境未迁移）。计数和阅读以 [提醒需求](../01_requirements/attention_module.md)、[提醒 API](../03_api/attention_api.md) 和 [验收记录](../08_frontend/qa/commerce-attention-review.md) 为准；P1.3 资金结果、P1.4 联合/真机与微信阶段仍待执行。

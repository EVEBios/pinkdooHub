# 可选预约套餐 · Code Review Report

日期：2026-09-13。范围：当前工作区的预约增量；未提交、未发布、未迁移持久数据库。既有未提交的主页、扫码开台与发布相关变更保留，不属于本报告的实现归属。

## Changes

- 创建入口和表单：`miniapp/src/pages/reservations/`、`pages/reservation-create/`；新增懒加载 `package_selector.tsx`，完整规格单选或全部省略，日期／开始时间优先。
- 状态与传输：`features/reservation/use_reservation_create.ts`、路由与登录白名单、`api/endpoints/reservations.ts`、生成的 OpenAPI 与 TypeScript 类型。
- 展示兼容：顾客和管理端的预约列表／详情均支持套餐字段及结束时间为 null；沿用旧有完整套餐预约。
- 后端：Reservation Schema、响应验证、Mapper、Validator、Service、Repository、Model；AccountLifecycleService 对无套餐有效预约使用预约日营业结束作为阻断截止。
- 结构变更：M10 将 8 个现有字段放宽为 nullable，保留外键及旧记录。回退遇到任何不完整套餐数据时阻断，不伪造套餐、时长或费用。

## Architecture Check

通过本次差异审查。API → Service → Repository → Model 分层保持；可选套餐逻辑在 Service／Validator，日期与店休、用户状态、审计仍在既有事务内。未新增业务 Service 互调。无套餐预约不查询或锁定 Product／Option；账户生命周期检查通过 Repository 完成。

## Security and Data Check

通过本次差异审查及相关测试。仅当前有效普通顾客创建，账户联系电话规则保留；他人详情隐藏，管理详情保留既有权限。请求中的 Option ID 必须合法；响应套餐字段严格全空或完整，防止缺失数据被当作零价。创建成功／结果未知冻结重复提交，商品接口故障不能阻断不选套餐的预约。临时验收使用合成数据，无真实付款或用户消息。

## Documentation Check

已同步预约需求与 API、数据库设计／DBML、前端集成契约与测试策略、迁移流程、changelog。Product Design 视觉结论和证据见 [design-qa.md](../../../design-qa.md#2026-09-13--新建预约与可选完整套餐)。

## Validation

- 后端全套：首次在受限沙盒中 3142 passed、39 skipped；4 个失败均为本机端口绑定权限限制。相同 4 个用例在获准的沙盒外定向重跑，全部通过。合计 3146 个通过，39 个条件跳过；不得把跳过的 MySQL 用例计入通过。
- 预约定向：94 passed、10 skipped；新增无套餐 HTTP 创建／审核／取消／混合列表、权限隐藏、店休、最晚时段、提前量、全空快照、事务回滚、账户生命周期边界与迁移降级阻断覆盖。
- 前端全套：103 suites、772 tests 通过（含新增顾客／管理列表与详情 null 展示回归）。
- TypeScript、改动范围 ESLint／Stylelint、OpenAPI 生成类型一致性、`git diff --check` 通过。
- 微信生产构建与 H5 构建通过；H5 保留既有 bundle size 提示。微信产物未上传，本地 H5 构建仅指向一次性验收 Origin。
- 本地 Playwright：真实登录和新建入口、日期控件、选套餐／清除选择、完整套餐提交、商品接口 503 时无套餐提交，以及 320／390／768／1280 宽度布局。交互用真实临时后端，商品失败只在该 HTTP 边界注入；无未处理页面异常。

## Action Items and Compatibility

- 无新增依赖，无版本号变更。
- M10 目前只有离线生成及结构／回退护栏检查，尚未运行 MySQL 迁移验收。SQLite 临时库按模型生成，用于功能验证，不是旧库迁移证据。
- 部署前需要在另行授权的可销毁 MySQL 上验证 M9 → M10、约束与回退阻断，再按项目发布流程协调数据库、服务端、顾客端和管理端升级。
- 旧前端的非空解析不能读取新建无套餐预约。公开旧客户端共存时，需要先完成兼容客户端覆盖／接口版本策略；本轮没有假定开关或静默降级。
- 已有无套餐记录后，不可直接回退旧非空 Schema／旧客户端；保持兼容读写和 nullable 数据结构，不删除历史或补造套餐。
- 真实商品照片裁切、微信开发者工具／真机和屏幕阅读器未在本轮复验。本地 H5 布局与交互证据不外推到这些环境。
- Gate A 状态、受保护 pending 和既有发布证据未变。

## Resource Cleanup

本次临时 Uvicorn 已优雅退出；精确检查先后启动的 PID 41851／41947／43301／43485 和失败浏览器 PID 42963 均不存在，18867 无监听，也没有带本次临时目录标识的进程。所有 Playwright 脚本通过 finally 关闭浏览器。两个临时 Chrome 标签页和一个内置浏览器标签页已关闭并用浏览器清单复核，用户原有标签页保留。临时 SQLite、内存 Redis、测试登录态、脚本与日志已清理，最终截图和本报告保留。未创建子代理；无已知需要继续回收的任务资源。

## 后续：本地旧 SQLite 的 422 修复（2026-09-13）

用户实际提交不选套餐的预约时，旧 `db.sqlite3` 返回 `NOT NULL constraint failed: reservations.scheduled_end_at`。模型更新和 development 的 generate_schemas 不会放宽已有字段，因此前面的新建隔离库验收不能替代旧库升级。

获得用户对备份、暂停后端、更新本地持久库和恢复服务的明确授权后，已完成本机 `db.sqlite3` 的专用 SQLite 表重建。在只读备份副本演练通过后暂停原 Uvicorn 及 reload 子进程，生成权限 0600 的备份 `backups/local-sqlite-migrations/reservation-m10-before-20260913T112255Z.sqlite3`。通过单个事务仅放宽 8 个套餐字段的 NOT NULL，保留原列类型、默认值、外键、5 个索引和自增序号；迁移前后所有 26 张业务表逐行摘要一致，8 条预约完整保留，integrity_check=ok，foreign_key_check=0。

恢复后的数据库已通过一次完整空套餐 INSERT 的事务回滚探测，探测没有留下预约或推进自增序号；恢复的本地 API 返回 HTTP 200 且支持可选套餐。后端按用户要求继续运行于 127.0.0.1:8000（恢复时 reload PID 45937、worker PID 45939）。备份有意保留且已由 Git 忽略。未执行 MySQL/Aerich M10、未改变发布环境或 Gate A 状态。

这条记录补充前面的首次交付状态：本地 SQLite 已修复；MySQL 迁移验收和其他持久环境升级仍未完成。此后若已有无套餐新记录，不能将备份直接覆盖回当前数据库，否则会丢失备份后写入的数据。

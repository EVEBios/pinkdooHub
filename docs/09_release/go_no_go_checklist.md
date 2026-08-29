# 微信发布 Go/No-Go Checklist

> **Status:** Not Authorized — Gate A 清单已建立
> **Last Updated:** 2026-08-29
> **Current Scope:** 微信小程序内部测试版（Gate A）

本清单是发布决策索引，不替代 CI、演练或验收证据。勾选项必须附证据链接、执行时间和责任人；“本机试过”“历史通过”“应该没问题”不能勾选。Phase 9.1 只建立清单，不授权微信上传、体验版分发、提审或公开发布。

## 1. Gate A：内部微信测试版

### 1.1 范围、候选与可追溯性

- [x] RDR-001 冻结为微信单平台、受邀内部测试、不可公开；
- [x] Phase 9.1 当前基线审计和八类交付物已建档；
- [x] 所有责任角色已映射为 Yijie Shen；
- [x] 项目负责人 Yijie Shen 已于 2026-08-29 Review 并确认 Phase 9.1 Complete；
- [ ] Gate A RC 建立前填写计划窗口和当次审批时间；
- [ ] RC Git SHA 工作树干净，后端/前端/微信版本映射明确；
- [ ] 后端与 `weapp` artifact 均来自同一已通过 CI 的 SHA，并记录 checksum；
- [ ] OpenAPI 摘要、运行时版本、微信开发者工具/上传工具版本已记录；
- [ ] 体验版名称、界面和测试说明明确标识“内部测试”，无公开承诺。

### 1.2 CI 与代码质量

- [ ] backend-sqlite：完整 pytest 通过，跳过项仅限已声明 MySQL-only；
- [ ] backend-mysql-release：专用 MySQL 8+、0→当前迁移及 9 项门槛通过；
- [ ] frontend-quality：TypeScript、ESLint、Stylelint、Jest 通过；
- [ ] openapi-contract：导出、固定 JSON、类型生成和 clean diff 通过；
- [ ] weapp-build：受控 Origin、包体、分包、warning、Secret/占位域名扫描通过；
- [ ] repository-hygiene：无意外生成物、缓存、数据库、上传文件或敏感信息；
- [ ] dependency-audit：Python/npm 报告齐全，微信可达高风险已关闭或有合规例外；
- [ ] Node/npm/Python/Taro 支持版本由仓库和 CI 固定。

### 1.3 环境、HTTPS 与 Secret

- [ ] 测试 API Origin、DNS、证书、续期责任和目标 AppID 已冻结；
- [ ] 微信后台 request/upload/download 合法域名与实际调用一致；
- [ ] 生产语义启动强制 `APP_DEBUG=false`、MySQL、随机 JWT 和必要配置；
- [ ] MySQL、Redis 和图片存储均为 Gate A 专用/受控资源；
- [ ] Secret inventory 已映射到实际保管系统、读取主体、轮换和责任人；
- [ ] 前端源码、artifact、日志和 source map 无 Secret；
- [ ] source map 上传、访问和保留策略已批准；
- [ ] 日志不输出密码、Token、完整 Redis URL、AppSecret、私钥或个人敏感信息。

### 1.4 迁移、备份与恢复

- [ ] 空 MySQL 8+ 执行 0→1→2 并核验版本、表、约束、索引和 opening balance；
- [ ] 迁移 0/1 的代表性数据升级到当前版本，关键业务数据不漂移；
- [ ] 迁移前备份在独立实例恢复，Schema、行数、抽样聚合和启动通过；
- [ ] 可控部分失败演练完成，前滚/恢复决策符合 MySQL DDL 真实语义；
- [ ] 演练未连接共享 3306、开发 SQLite、持久/生产资源或使用 `--fake`；
- [ ] 演练资源、端口、临时目录和合成数据已按记录清理并复核。

### 1.5 运行时与运维

- [ ] FastAPI/Uvicorn 可启动、优雅停止、重启，错误不泄露配置；
- [ ] liveness 与 DB/Redis readiness 分离，依赖故障时不接业务流量；
- [ ] Redis 认证/网络边界和故障行为验证通过；
- [ ] 图片上传、HTTPS 读取、持久化、备份和恢复通过；
- [ ] SUPER_ADMIN bootstrap 一次性、幂等、可审计，初始凭据已安全处置；
- [ ] 日志可查询，错误、延迟和依赖故障至少有 Gate A 观察办法；
- [ ] 体验版测试人员、反馈入口、停用日期、数据清理和事故联系人明确。

### 1.6 微信与业务验收

- [ ] iOS 和 Android 真机记录设备、系统、微信、基础库和网络；
- [ ] request/upload/download、HTTPS 和合法域名在真机通过；
- [ ] Guest、普通用户、ADMIN、SUPER_ADMIN、禁用用户纵向链路通过；
- [ ] Product、Cart、创建订单、用户订单/取消、管理订单通过；
- [ ] Product 管理、图片、Inventory、Audit、用户禁用通过；
- [ ] access/refresh 失效、权限、资源隐藏和错误信封通过；
- [ ] 弱网、断网、网络恢复、前后台、锁屏、分包首次加载通过；
- [ ] 重复点击、上传中断和服务端成功/客户端未知有安全收敛证据；
- [ ] 所有 `FAIL/BLOCKED/GAP` 已关闭、延期到非当前 Gate或进入明确风险例外。

### 1.7 Gate A 决策

- [ ] 没有越权、Secret 泄漏、数据破坏、重复订单/库存错误或无法恢复的阻断缺陷；
- [ ] [risk_register.md](risk_register.md) 中所有 Gate A P0/P1 已关闭或满足例外规则；
- [ ] Yijie Shen 分别以测试负责人、技术负责人和项目负责人角色记录 Go 结论与时间；
- [ ] 上传/分发体验版已取得单独外部操作授权；
- [ ] 明确 Gate A 不授权提审或公开发布。

任一必需项未勾选，结论即为 **No-Go**。

## 2. Gate B：对外公开微信小程序追加门槛

Gate A 全部重新绑定公开 RC 后，还必须：

- [ ] 微信登录 code2Session、OpenID/UnionID、账号绑定/冲突/禁用/恢复通过；
- [ ] 登录/注册限流、refresh token 轮换/撤销/重放检测通过；
- [ ] Order create 服务端幂等及并发/unknown 结果通过；
- [ ] 若在线收款：微信支付下单、调起、验签、金额核对、通知幂等、查单、关闭、退款、对账和告警通过；
- [ ] 若不在线收款：用户文案、履约和订单状态不暗示已提供在线支付；
- [ ] 正式 MySQL/Redis/图片、Secret、备份恢复、监控告警和事故流程通过；
- [ ] 隐私保护指引、同意/撤回、账号注销/删除、数据保留和联系方式完成 Review；
- [ ] 小程序主体、类目、备案/适用要求、审核材料、审核账号与服务内容一致；
- [ ] 管理分包公开发布决策完成；
- [ ] 发布观察窗口、回滚/停写/恢复权限和联系人冻结；
- [ ] 取得提审和正式发布的分别授权。

## 3. 自动 No-Go 条件

以下任一情况无需等待表决，直接 No-Go：

- artifact、Git SHA、OpenAPI 或环境来源不能证明一致；
- CI 必需 Job 未运行、被无批准跳过或结果不可复核；
- 连接目标身份不明、备份未恢复验证或迁移状态无法解释；
- 存在越权、Secret/个人敏感信息泄漏、数据破坏或不可恢复风险；
- 订单/库存/支付出现重复、伪造、金额不一致或 unknown 无安全处置；
- 真机 HTTPS、合法域名、request/upload/download 不通；
- Gate A 试图公开分发，或 Gate B 缺少登录/支付（适用时）/安全/隐私硬门槛；
- 实际包与已测试包不同，或在开发者电脑手工修改后上传。

## 4. 决策记录模板

```text
Decision ID：
Gate：A / B
RC / Git SHA / CI run / artifact checksum：
目标环境 / 微信版本：
Checklist 证据索引：
未关闭风险与例外：
决定：GO / NO-GO
决定理由：
测试负责人：Yijie Shen（待签署）
技术负责人：Yijie Shen（待签署）
项目负责人：Yijie Shen（待签署）
外部操作授权范围：无 / 上传体验版 / 提审 / 正式发布
决定时间与观察窗口：
停止、回滚或恢复触发条件：
```

GO 只授权记录中写明的 Gate、RC、环境和外部操作；不能自动延伸到下一 Gate、另一个 SHA、提审或正式发布。

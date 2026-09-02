# 微信发布 Go/No-Go Checklist

> **Status:** No-Go / Not Authorized — 备案前服务器/自动化/治理已通过，真实域名与真机仍待完成
> **Last Updated:** 2026-09-02
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
- [x] 备案前预 RC 已绑定 `c4d27a8...`、Node 24.13.0/npm 11.6.2、开发者工具 Stable 2.02.2608060、不可发布 `.test` Origin、97 文件/603,624 bytes、0 source map 和 manifest `aeb81ef...`；该项不替代上面的真实 RC；

### 1.2 CI 与代码质量

- [x] backend-sqlite：Phase 9.3 候选 Run 33408135841 通过，跳过项仅限已声明 MySQL-only；
- [x] backend-mysql-release：专用 MySQL 8+、0→当前迁移及 9 项门槛通过；
- [x] frontend-quality：TypeScript、ESLint、Stylelint、Jest 通过；
- [x] openapi-contract：导出、固定 JSON、类型生成和 clean diff 通过；
- [x] weapp-build：受控非发布 Origin、包体、分包、warning、Secret/占位域名策略扫描通过；
- [x] repository-hygiene：无意外生成物、缓存、数据库、上传文件或敏感信息；
- [x] dependency-audit：Python/npm 报告齐全，微信可达高风险已关闭或有合规例外；
- [x] Node/npm/Python/Taro 支持版本由仓库和 CI 固定。

### 1.3 环境、HTTPS 与 Secret

- [ ] 测试 API Origin、DNS、证书、续期责任和目标 AppID 已冻结；
- [ ] 微信后台 request/upload/download 合法域名与实际调用一致；
- [x] 生产语义演练启动强制 `APP_DEBUG=false`、MySQL、随机 JWT 和必要配置；
- [x] Phase 9.3 MySQL、Redis 和图片存储均为专用/受控资源；
- [x] Gate A Secret inventory 已映射到 Root 文件边界、精确权限/读取主体、轮换/泄漏触发和责任人；Gate B 集中 Secret Manager 单独延期；
- [x] 当前备案前候选的前端源码/artifact 与持久主机 24 小时日志扫描无 Secret 命中；
- [x] Gate A source map 策略已批准为不生成、不上传；项目配置和当前预 RC 均为 0 source map；
- [x] 持久主机日志无密码、Token、完整 Redis URL、AppSecret、私钥或高置信敏感模式命中，成功 Record 只保存聚合；

### 1.4 迁移、备份与恢复

- [x] 空 MySQL 8+ 执行 0→1→2 并核验版本、表、约束、索引和 opening balance；
- [x] 迁移 0/1 的代表性数据升级到当前版本，关键业务数据不漂移；
- [x] 迁移前备份在独立实例恢复，Schema、行数、抽样聚合和启动通过；
- [x] 可控部分失败演练完成，前滚/恢复决策符合 MySQL DDL 真实语义；
- [x] 演练未连接共享 3306、开发 SQLite、持久/生产资源或使用 `--fake`；
- [x] 演练资源、端口、临时目录和合成数据已按记录清理并复核。
- [x] 持久 Gate A 在代表性用户/Product/图片/订单/库存/Audit 数据上完成非空备份与无端口独立恢复，来源服务恢复健康且临时资源归零；
- [x] 保留期、删除审批、恢复授权和周期演练频率已冻结；Backup `20260902t014211z` 的加密异机副本已完成导出后解密/来源 checksum/Restore PASS 复核。

### 1.5 运行时与运维

- [x] FastAPI/Uvicorn 可启动、优雅停止、重启，错误不泄露配置；
- [x] liveness 与 DB/Redis readiness 分离，依赖故障时不接业务流量；
- [x] Redis 认证/网络边界和故障行为验证通过；
- [x] 图片上传、HTTPS 读取、持久化、备份和恢复通过；
- [x] SUPER_ADMIN bootstrap 一次性、严格重放、可审计，初始凭据已安全处置；
- [x] 日志可按精确 Compose project 查询；24 小时请求/4xx/5xx/时延聚合、MySQL/Redis 摘流量与恢复、App 重启和敏感扫描已真实通过；
- [x] 初始测试人员、allowlist、反馈入口、14 日窗口/停用规则、数据清理和事故联系人已冻结。

### 1.6 微信与业务验收

- [ ] iOS 和 Android 真机记录设备、系统、微信、基础库和网络；
- [ ] request/upload/download、HTTPS 和合法域名在真机通过；
- [x] Guest、普通用户、ADMIN、SUPER_ADMIN、禁用用户服务端 HTTPS 纵向链路通过；
- [x] 当前 Git SHA 的自动化/loopback 证据覆盖 Product、Cart、Order、Product 管理、图片、Inventory、Audit、用户禁用、Token、权限、错误和重复操作；下面的微信 RC 人工/真机项仍不得据此勾选；
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

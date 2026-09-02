# Phase 9 微信小程序发布规划

> **Document Version:** v0.2
> **Status:** Phase 9.1–9.3 Complete; Phase 9.4 进行中（Gate A 仍为 No-Go）
> **Last Updated:** 2026-09-02
> **Release Scope:** 本版只发布微信小程序（`weapp`）

本文把“多端、CI 与发布”收敛为本版可执行的微信单平台路线。Phase 9 不是一次性把代码上传到微信，而是依次建立发布目标、可重复门槛、隔离演练、内部测试版和公开发布门。每一阶段都必须产生可复核证据；历史测试通过、单次本机构建或开发者工具 Functional 不能替代当前候选版本的发布证据。

微信平台规则会变化。合法域名、网络、登录、隐私、包体和提审要求在每个 Release Candidate（RC）冻结时以[微信开放文档](https://developers.weixin.qq.com/miniprogram/dev/framework/)和微信公众平台后台当时展示的规则为准，本文件只冻结项目自己的工程边界。

---

## 1. 已冻结的发布目标

### 1.1 平台与发布通道

本版冻结为：

- 唯一发布平台是微信小程序，构建目标为 `weapp`；
- 第一交付目标是**内部微信测试版**，通过开发版/体验版向明确的测试人员开放；
- 内部测试版通过后，是否进入**对外公开微信小程序**使用独立 Go/No-Go 门，不因内部测试通过而自动公开；
- 支付宝、抖音和 H5 不进入本版开发范围、CI 阻断项、Functional 矩阵或发布承诺；
- 现有跨端源码和构建命令可以保留，但不把未验证的平台描述为本版已支持能力。

### 1.2 两道发布门

| 发布门 | 用户范围 | 身份与支付 | 目的 | 是否允许公开 |
|--------|----------|------------|------|--------------|
| Gate A：内部微信测试版 | 开发、测试和受邀业务人员 | 暂时沿用账号密码；订单由 ADMIN+ 人工确认 Paid | 验证真实 HTTPS、MySQL、Redis、图片、迁移、真机和运维链路 | 否 |
| Gate B：对外公开微信小程序 | 不受控公众用户 | 普通用户使用微信登录；若在线成交或收款，必须完成微信支付闭环 | 商业与公开使用 | 仅在全部公开发布硬门槛通过后 |

Gate A 的账号密码和人工确认 Paid 只是一条受控测试闭环，不得在宣传、审核材料或用户界面中暗示为正式微信登录或在线支付。若 Gate B 不提供在线支付，则必须同步冻结不收款的业务模式和用户可见文案；不能保留一个看似可在线购买、实际依赖管理员线下改 Paid 的公开流程。

### 1.3 当前版本的非目标

Phase 9.1 不实现以下能力：

- 微信登录、微信支付或退款；
- Order create 服务端幂等键；
- 登录/注册限流、refresh token 轮换；
- 云厂商、容器平台、对象存储、CDN、监控或 Secret Manager 选型；
- 正式域名购买、DNS 切换、证书签发或微信后台配置；
- 持久数据库迁移、Git tag、Release、微信上传、提审或发布；
- 支付宝、抖音或 H5 的构建修复、CORS、Functional 或安全债处理。

这些事项在 9.1 中只记录依赖、验收标准和负责人，不提前绑定商业平台或扩大外部变更权限。

---

## 2. Phase 9 子阶段

| 子阶段 | 目标 | 主要交付物 | 退出条件 |
|--------|------|------------|----------|
| 9.1 发布目标与发布基线审计 | 冻结“发布什么、暂不发布什么、现状缺什么” | 本规划、配置清单、风险登记、CI 蓝图、演练 Runbook 草案、验收矩阵 | 所有条目有 `pass/gap/deferred/blocker` 状态；Gate A 与 Gate B 不再混写 |
| 9.2 CI 与可重复构建 | 把人工门槛变成稳定流水线 | 后端 SQLite、MySQL-only、前端、OpenAPI、微信构建、依赖/Secret/生成物检查 | 干净 checkout 可重复通过；失败能定位；产物关联 Git SHA |
| 9.3 隔离发布演练 | 在生产相似但可销毁的环境验证部署和恢复 | 0→当前迁移、受支持升级场景、备份恢复、应用启动、Redis、图片、管理员初始化、Smoke、回滚报告 | 演练证据完整；没有使用开发 SQLite、共享数据库或手工补状态 |
| 9.4 微信内部测试版 | 交付受控体验版并完成真机 Functional | RC 清单、微信构建产物、iOS/Android 真机报告、弱网/前后台/上传报告、缺陷处置 | Gate A 全部通过；仍明确标记“不可公开” |
| 9.5 公开发布安全与身份 | 关闭公众身份、安全和生产运维缺口 | 微信登录、账号关联规则、限流、refresh 轮换、Secret 管理、监控告警、生产存储、隐私与用户权利方案 | 公开身份与数据处理经过测试和 Review |
| 9.6 微信交易闭环 | 仅在本版需要在线成交/收款时实施 | Order create 幂等、微信支付下单/回调/查单、金额校验、通知幂等、退款与对账方案 | 支付正常、重复、延迟、伪造、未知结果、退款和对账全部通过 |
| 9.7 公开 RC 与发布 | 完成提审、灰度、发布后观察和回滚准备 | 最终 RC、审核材料、Go/No-Go 记录、发布记录、健康检查与观察报告 | Gate B 全部通过并取得明确发布授权 |

9.5 和 9.6 可以先做设计审计，但不得与 9.1 混成一个大提交。若最终业务决定只交付内部测试版，Phase 9 可以在 9.4 形成一个明确的内部版本里程碑，9.5–9.7 保持未开始，而不是把它们误标为已完成。

---

## 3. Phase 9.1 基线审计

### 3.1 当前证据与缺口

| 领域 | 当前证据 | 9.1 状态 | 进入 Gate A 前的动作 |
|------|----------|----------|----------------------|
| 微信业务 Functional | Phase 5–8 已在微信开发者工具覆盖 Guest、用户、ADMIN、SUPER_ADMIN 的当前能力 | `pass-with-limitations` | 在当前 RC、真实 HTTPS、MySQL/Redis 和真机上重跑；不能复用本地 SQLite 结论 |
| 前端静态与单测 | PR #2 Run 33355935212 从干净 checkout 完成 TypeScript、ESLint、Stylelint、61 套件/387 项 Jest | `verified-pr-ci-9.2.6` | Gate A RC 继续在冻结依赖和当前 SHA 重跑 |
| 微信生产构建 | PR #2 Run 33355935212 使用保留 CI Origin 构建并扫描：97 文件/603,619 bytes，主包 425,527 bytes、`admin` 分包 178,092 bytes；manifest 明确不可发布并绑定配置 SHA | `verified-pr-ci-9.2.6 / non-release` | Gate A 另用批准 Origin 生成并绑定 RC |
| 非微信平台 | 历史上有四端构建记录 | `deferred` | 不作为本版门槛，不继续宣称支付宝、抖音或 H5 本版可发布 |
| OpenAPI | PR #2 Run 33355935212 完成 CLI UTF-8/CP1252 契约、真实 FastAPI 导出字节比较与类型漂移检查 | `verified-pr-ci-9.2.6` | RC 继续从当前 FastAPI 导出并检查干净 diff |
| 后端 SQLite | PR #2 Run 33355935212 的 `backend-sqlite` 从干净 checkout 通过；本地完整基线为 `1507 passed, 9 skipped` | `verified-pr-ci-9.2.6` | MySQL-only 继续由独立 Job 执行 |
| MySQL-only | PR #2 Run 33355935212 使用固定 MySQL 8.0.46、回环 13306、专用 Schema 真实执行 Aerich 0→1→2 与 9 项门槛，并保存 cleanup artifact | `verified-pr-ci-9.2.6` | 发布演练仍需 9.3 生产相似环境、备份恢复和失败处置 |
| 迁移 | Phase 9.3 DR-01～DR-03 在 MySQL 8.0.46 完成空库、m0 与 m1→当前，数据/快照/opening balance 保持 | `verified-9.3` | 如未来出现待接管数据库，先只读审计其 Schema/Aerich 状态，再定义升级起点 |
| 现有生产升级 | 当前没有已发布、由项目确认接管的持久生产 MySQL 基线 | `not-applicable-now` | 不虚构“现有生产升级已通过”；首次上线按空库部署，未来每次发布建立 N-1→N 演练 |
| 备份与恢复 | DR-04 数据库/图片备份恢复到独立 MySQL/volume，restore-app Ready 与轮换后登录通过；DR-05 部分失败恢复通过 | `verified-9.3` | Gate A RC 继续绑定实际测试环境备份责任；正式生产另行冻结持久备份策略 |
| API Origin | `.env.production` 仍是 `.example.invalid` 占位 Origin | `blocker` | 冻结测试与正式 HTTPS Origin；构建时显式注入且扫描产物无 localhost/占位域名 |
| 微信合法域名 | `project.config.json` 开启 `urlCheck` | `gap` | 在微信后台分别配置实际使用的 request/upload/download 域名并真机验证 |
| HTTPS/DNS | 生产配置要求 HTTPS，但尚无已冻结域名和证书证据 | `blocker` | 冻结 DNS、证书续期和 TLS 检查；发布前从外网与真机验证 |
| Redis | DR-06 在认证 Redis 8.0.1 验证启动、故障 503、恢复 Ready 和优雅重启 | `verified-9.3` | Phase 9.4 继续使用冻结的测试环境；Gate B 再冻结正式高可用/TLS 策略 |
| 健康检查 | 9.3.1 契约与 DR-06 真实 MySQL/Redis 故障/恢复均通过，Liveness 与 dependency-aware Readiness 分离 | `verified-9.3` | 9.4 在真实测试 Origin 复核；Gate B 补监控告警 |
| 图片 | DR-09 三类上传/HTTPS 读取、DR-06 重启保持、DR-04 独立备份恢复均通过 | `verified-gate-a-9.3` | Gate B 冻结对象存储/CDN 或等价高可用方案 |
| 日志 | Redis 连接日志已在 9.2.2 改为安全目标摘要并通过脱敏测试 | `mitigating` | CI 重跑脱敏契约；继续定义采集、保留、检索和告警 |
| Secret | 9.2.2 production fail-fast 已覆盖 JWT/Redis/图片地址且错误隐藏输入；`.env` 被忽略 | `mitigating` | CI 重跑配置契约；建立 Secret 清单、注入、轮换、最小权限和 artifact 泄漏扫描 |
| 管理员初始化 | DR-07 隔离演练与 2026-09-02 真实 Gate A 均完成首次/严格重放、唯一用户/Audit、登录、凭据轮换、会话撤销和 Secret 清理 | `verified-gate-a-bootstrap` | 保留脱敏 Record；RC 继续验证 SUPER_ADMIN 高权限边界，不复用初始化 Secret |
| CI | Phase 9.3 最终候选 `136a8bd...` 的 Run 33408135841 在干净 checkout 完成 8/8 Job | `verified-9.3-candidate` | 9.4 RC 需重新绑定真实 Origin/产物，不能复用演练短期证书 |
| 依赖审计 | `pip-audit==2.10.1` 的 1 条 HS256 不可达例外与 npm 10 包/5 公告精确策略均在 Run 33355935212 通过，策略于 2026-11-30 到期 | `accepted-until` | 到期前升级上游或重新审批，不得破坏性强制降级 |
| E2E | 有大量前端纵向 Jest 和人工 Functional，但没有生产相似微信自动 E2E | `gap` | 冻结最低 Smoke/Functional；自动化能力单独 Spike，不用脆弱脚本伪装已覆盖 |
| 公开身份/交易 | 只有用户名密码与 ADMIN+ 人工 Paid | `Gate B blocker` | 9.5/9.6 分别实施微信身份和交易闭环；Gate A 不要求但必须限制测试人群 |
| 安全与合规 | 已知缺少限流、refresh 轮换、隐私/审核材料 | `Gate B blocker` | 按 9.5 的公开发布门关闭，不由 UI 或已有测试替代 |

`pass-with-age` 表示历史证据证明方向可行，但结果未绑定即将发布的 Git SHA、依赖锁文件、环境和构建产物，因此不能直接作为 RC 证据。

### 3.2 9.1 必须形成的文件化交付物

9.1 的八类交付物已保存在 [发布文档目录](../09_release/README.md)，所有责任角色已统一映射为 Yijie Shen；其已于 2026-08-29 以项目负责人角色完成范围与关闭 Gate Review：

1. [Release Decision Record](../09_release/release_decision_record.md)：发布平台、Gate、目标用户、功能范围、身份方式、是否在线收款、数据边界和授权规则。
2. [Environment Matrix + Secret Inventory](../09_release/environment_and_secrets.md)：四级环境、Origin、MySQL、Redis、图片、日志、Secret 所有者与轮换字段。
3. [CI Gate Matrix](../09_release/ci_gate_matrix.md)：Job、命令、输入、产物、阻断规则和已知跳过项。
4. [Release Drill Runbook](../09_release/release_drill_runbook.md)：备份、迁移、验证、启动、Smoke、失败处置、恢复和清理。
5. [Functional/Smoke/E2E Matrix](../09_release/wechat_acceptance_matrix.md)：角色、业务、设备、网络、生命周期与证据等级。
6. [Risk Register](../09_release/risk_register.md)：概率、影响、信号、缓解、责任角色、截止 Gate 和状态。
7. [Go/No-Go Checklist](../09_release/go_no_go_checklist.md)：只接受可追溯证据的 Gate A/Gate B 决策清单。
8. [2026-08-29 基线审计](../09_release/baseline_audit_2026-08-29.md)：本次命令、版本、产物、缺口和平台规则证据。

---

## 4. 环境与配置基线

### 4.1 环境矩阵

| 部署层级 | 前端业务环境 | 后端 `APP_ENV` | 数据库 | Redis | Origin/域名 | 数据规则 |
|----------|--------------|----------------|--------|-------|-------------|----------|
| 本地开发 | `development` | `development` | SQLite | 本地 Redis | HTTP localhost，可关闭微信域名校验 | 可丢弃，不产生发布证据 |
| CI | `testing` | `testing` | 隔离 SQLite + 专用 MySQL 8+ Job | 隔离服务 | CI 内部地址 | 每次重建，不访问共享资源 |
| 发布演练 | `production` 构建模式 | `production` 配置语义 | 生产相似、可销毁 MySQL 8+ | 生产相似隔离实例 | 短期受信 HTTPS；微信合法域名/真机留到 9.4 | 使用脱敏/合成数据，可完整备份恢复 |
| 正式生产 | `production` | `production` | 持久 MySQL 8+ | 持久 Redis | 正式 HTTPS 域名并加入微信白名单 | 受控迁移、备份、监控和数据保留 |

发布演练和生产可以使用不同基础设施实现，但配置语义必须相同。不得把 `APP_ENV=production` 当作安全保证；仍需逐项验证 `APP_DEBUG=false`、MySQL、Redis、JWT、图片地址、日志和网络边界。正式应用启动不得自动建表。

### 4.2 配置清单

以下清单冻结“要配置什么”，不冻结具体供应商或 Secret 值：

| 配置 | 是否 Secret | 前端可见 | Gate A | Gate B |
|------|-------------|----------|--------|--------|
| 微信 AppID | 否 | 可以 | 固定到目标小程序账号 | 同一正式主体和目标账号 |
| 微信 AppSecret | 是 | 禁止 | 若未接微信登录可不注入 | 仅后端 Secret 系统，最小权限和可轮换 |
| API Origin | 否 | 是 | 真实测试 HTTPS Origin | 正式 HTTPS Origin |
| request/upload/download 合法域名 | 否 | 平台配置 | 按真实调用配置并真机验证 | 正式域名，发布前再次复核 |
| DB host/user/password/name | 部分是 | 禁止 | 隔离 MySQL | 生产 MySQL，独立最小权限账号 |
| Redis URL/凭据 | 是 | 禁止 | 隔离 Redis | 生产 Redis，不在日志显示完整 URL |
| JWT Secret | 是 | 禁止 | 测试专用随机值 | 生产专用随机值，定义轮换与旧 Token 处置 |
| 微信支付商户号 | 否/受限配置 | 不应由业务页面决定 | 不需要 | 仅在线收款时需要 |
| 微信支付私钥/API 密钥/证书材料 | 是 | 禁止 | 不需要 | 仅后端 Secret 系统，轮换、到期和权限告警 |
| 图片存储目录/Origin | 部分是 | 只暴露访问 URL | 持久卷或隔离对象存储 | 对象存储/CDN 或经 Review 的等价方案 |
| 日志级别与采集端点 | 采集凭据是 | 禁止 | INFO、脱敏、可查询 | INFO、脱敏、告警、保留策略 |
| source map 上传凭据 | 是 | 禁止进入产物 | 如启用则只在 CI | 同左，并限制下载权限 |

### 4.3 前端产物检查

每个微信 RC 必须检查：

- `TARO_APP_APP_ENV=production`，`TARO_ENV=weapp`；
- API Origin 是预期 HTTPS Origin，且没有 localhost、IP、`.example.invalid` 或测试域名混入正式产物；
- AppSecret、JWT Secret、数据库/Redis 凭据、支付密钥和私钥未进入源码、source map、日志或构建产物；
- `project.config.json` 与目标 AppID、`miniprogramRoot` 和构建目录一致；
- 主包、`admin` 分包和总包体满足 RC 当日微信规则，并记录实际大小而非只记“构建通过”；
- 正式包是否包含管理分包经过显式决定。若保留，必须验证普通用户不可发现/不可调用管理能力，后端 ADMIN+ 仍是授权事实；若移除，必须另有受控管理入口，不能破坏运营闭环；
- source map 的上传、访问和保留策略明确，不能因排错便利公开源码或配置。

---

## 5. CI 门槛蓝图

### 5.1 必须 Job

| Job | 关键动作 | 阻断条件 | 证据 |
|-----|----------|----------|------|
| backend-sqlite | Python 3.10、锁定依赖、`pytest tests/ -q` | 任一失败；MySQL-only 以外出现跳过且无批准 | pytest 日志与汇总 |
| backend-mysql-release | 启动隔离 MySQL 8+、执行 Aerich 0→当前、运行 9 项 MySQL 门槛 | 迁移、并发、1205 重试、HTTP smoke 或 EXPLAIN 任一失败 | MySQL 版本、迁移版本、pytest 报告 |
| frontend-quality | `npm ci --legacy-peer-deps`、typecheck、ESLint、Stylelint、Jest | error、warning 超过已批准白名单、测试失败 | Node/npm 版本和测试报告 |
| openapi-contract | 从 FastAPI 导出 OpenAPI、比较固定 JSON、运行类型漂移检查 | OpenAPI 或生成类型有未提交漂移 | diff 和 schema 统计 |
| weapp-build | 使用受控 Origin 执行 `npm run build:weapp` | 构建失败、Secret/开发 Origin 命中、包体越界、未批准 warning | `dist/weapp` artifact、大小清单、Git SHA |
| repository-hygiene | 生成后 `git diff --exit-code`、敏感信息和意外生成物检查 | 工作树漂移、Secret、数据库、上传或缓存进入候选 | diff/扫描报告 |
| dependency-audit | Python/npm 依赖完整性、漏洞和许可证结果记录 | 直接或微信运行时可达的未处置高风险；锁文件不可复现 | 原始报告与处置记录 |

2026-08-29 官方 registry 基线报告 10 项（4 moderate、1 high、5 critical），链路同时包含直接 `@tarojs/components`/swiper、构建工具和 H5 依赖，当时不能证明全部是 H5-only。9.2.5 已逐项区分为“受影响 serve API 未启用的 build-time”“H5-only”和“当前微信源码/产物未使用的 npm swiper 实现”，并以 2026-11-30 到期的精确策略 fail-closed；不能静默忽略，也不能用会破坏性降级 Taro 3.x 的 `audit fix --force` 伪装清零。

### 5.2 触发与合并规则

- Pull Request：所有必须 Job 都运行；在确认真实耗时前不做路径跳过。
- `main`/发布分支：重跑全部 Job，生成不可变微信构建 artifact。
- RC：从已通过 CI 的同一 Git SHA 取 artifact；不得在开发者电脑修改后重新构建一个未验证包。
- 定时任务：重跑依赖审计和可选兼容性检查；支付宝、抖音、H5 结果只能作为未来信息，不阻断本版微信 RC。
- 上传微信体验版、提交审核和正式发布属于外部状态变更，必须有人工审批；9.2 默认只构建和保存产物，不自动发布。

### 5.3 版本与可追溯性

每个 RC 记录：

- 后端 `APP_VERSION`；
- `miniapp/package.json` 版本；
- Git commit SHA 和工作树必须干净；
- Python、Node、npm、Taro、微信开发者工具/上传工具版本；
- OpenAPI 摘要；
- 微信代码上传版本和备注；
- CI run、artifact checksum、目标环境和发布时间。

在版本策略正式冻结前，不把后端 `0.6.0`、前端 `1.0.0` 和微信上传版本假定为同一个版本。推荐用一份 Release Record 显式映射，而不是强行让三个系统共享一个格式。

---

## 6. 隔离发布演练 Runbook

### 6.1 演练场景

至少完成：

1. **首次部署**：全新 MySQL 8+ 空 Schema 执行 0→1→2，验证 Aerich 版本、表、约束、索引和期初库存流水。
2. **受支持升级**：在迁移 0 和迁移 1 的代表性数据状态分别升级到当前版本，验证 Product、Order、库存余额、opening balance 和审计不漂移。
3. **备份恢复**：升级前备份，在独立新实例恢复，验证 Schema、关键表行数、抽样业务聚合和可启动性。
4. **迁移部分失败**：模拟可控失败，确认 MySQL DDL 隐式提交后的真实状态，按 Runbook 前滚或从备份恢复，不假设事务自动回滚。
5. **应用切换**：启动 FastAPI/Uvicorn，验证 DB、Redis、静态图片、健康检查、优雅停止和再次启动。
6. **微信网络**：从体验版真机验证 request、upload、download、Token 刷新、图片和错误信封。
7. **管理员初始化**：用受控 bootstrap 建立首个 SUPER_ADMIN，首次登录后执行凭据处置；验证重复执行不会创建第二个初始化账号。
8. **基础 Smoke**：按第 7 节矩阵执行最小纵向链路。

如果现实中存在一套希望保留的 MySQL 数据库，它在只读 Schema、Aerich 版本、数据质量和备份审计前不属于“受支持升级基线”。SQLite 开发库不直接转换或冒充生产 MySQL 基线。

### 6.2 发布顺序

推荐顺序：

```text
冻结 RC Git SHA 与 artifact
        ↓
宣布维护/停写窗口（需要时）
        ↓
检查目标、连接身份、MySQL 版本和当前 Aerich 状态
        ↓
创建并验证备份
        ↓
执行迁移并逐项核验
        ↓
部署后端并等待 readiness
        ↓
执行 API/Redis/图片/角色 Smoke
        ↓
上传同一 RC 微信体验版并执行真机 Smoke
        ↓
Go / 前滚修复 / 从备份恢复
```

数据库迁移和应用回滚必须分开设计。应用二进制通常可以切回上一版本，但 Inventory downgrade 会删除流水表和运行后新增历史，不是无损回滚；一旦新版本开始写数据，优先停写并前滚修复。任何 downgrade 或恢复都需要单独授权。

### 6.3 演练证据

演练报告至少记录：

- 环境是如何隔离的，确认未连接 3306 共享实例、开发 SQLite 或生产资源；
- MySQL/Redis/运行时版本、迁移前后 Aerich 版本；
- 备份路径或快照 ID（不含凭据）、恢复验证和耗时；
- 每一步开始/结束时间、执行者、命令摘要、退出码和关键校验；
- Smoke 账号类型和合成数据，不记录密码或 Token；
- 失败注入、实际状态、选择前滚/恢复的依据；
- 演练资源的停止、端口释放、临时数据删除和复核结果。

---

## 7. Functional / Smoke / E2E 冻结矩阵

### 7.1 角色与纵向链路

| 角色/边界 | Gate A 最低 Smoke | RC Functional / E2E | Gate B 额外门槛 |
|-----------|------------------|---------------------|------------------|
| Guest | 启动、首页、Product 列表/详情、登录入口 | Content/Empty/Error/重试、分页筛选、图片失败占位 | 隐私入口、审核可见文案、未登录数据最小化 |
| 普通用户 | 账号登录、Session 恢复、登出 | 注册、主动/被动 refresh、Cart、Experience/Kit/混合创建、我的订单、Pending 取消 | 微信登录、账号绑定/冲突/禁用、refresh 轮换；在线收款时接微信支付 |
| ADMIN | 登录、管理入口、读取列表 | Order Paid/Completed、Product CRUD/Option/图片/上下架、Inventory 调整与流水、Audit、用户列表/禁用 | 正式凭据策略、最小权限、敏感操作告警和审核说明 |
| SUPER_ADMIN | 登录和 SUPER_ADMIN 端点 | 初始化、角色边界、不能被低角色禁用 | bootstrap 关闭/轮换、紧急访问流程和审计 |
| 被禁用用户 | 登录失败 | 已有 access/refresh 失效，客户端清理 Session，不触发 refresh 循环 | 微信身份关联后同样立即阻断 |
| Token 边界 | access 过期可刷新 | access/refresh 同失效、并发 refresh single-flight、时钟边界 | refresh 轮换、重放检测和撤销策略 |
| 权限边界 | 普通用户无管理入口 | 普通用户直调 ADMIN API 为 403；不存在的资源按契约隐藏 | 前端隐藏不替代后端授权；审核账号权限明确 |

### 7.2 业务矩阵

| 领域 | 必测行为 |
|------|----------|
| Product | Experience/Kit、列表/详情、Option 组合、Draft/Online/Offline/删除、图片 HTTPS/失败/预览 |
| Cart | Storage 恢复、坏缓存、数量/条目上限、Option 隔离、无库存 Kit、登录/登出策略 |
| Order create | Experience/Kit/混合、最后库存、库存不足、快速点击、网络 unknown、成功后 Cart 对账 |
| User Order | 分页/筛选、历史快照、owner-only、Pending 取消恢复库存、终态无取消、40921 收敛 |
| ADMIN Order | 组合筛选、详情、Pending→Paid→Completed、库存不变、竞态/unknown 不自动重发 |
| Product Admin | 创建/编辑/删除、Option 恢复原 ID、Kit 改价、图片生命周期、readiness、上下架和历史快照 |
| Inventory | 首次 201/重放 200、同意图同 key、正负调整、40932、两类流水、筛选/分页/Order 跳转、隐私字段 |
| Audit/User Admin | Product Audit、逻辑删除历史、ADMIN User 筛选、禁用事务/审计/旧 Token 阻断、角色层级 |

Gate B 在上述矩阵上增加微信身份和支付域，不另建一套绕开现有订单/库存事务的平行流程。

### 7.3 设备、网络与生命周期

每个 RC 至少覆盖：

- 一台受支持 iOS 真机和一台受支持 Android 真机；
- 常见屏幕、小屏、大字体、键盘遮挡和安全区域；
- Wi-Fi、移动网络、弱网、断网和网络恢复；
- 冷启动、热启动、前后台切换、锁屏、请求中断和分包首次加载；
- 上传中断、重复点击、服务端已成功但客户端未知、用户安全重试；
- Token 即将过期、请求中到期、refresh 失败；
- request/upload/download 合法域名与证书在真机生效，开发者工具关闭域名校验的结果不计入证据。

### 7.4 自动化分级

矩阵中的每项必须标成以下一种：

- `A`：CI 自动化，能绑定 Git SHA；
- `M`：RC 人工验证，有设备/环境/结果记录；
- `A+M`：自动化和真机都要求；
- `N/A`：本 Gate 不适用，并写原因；
- `GAP`：未覆盖，必须有负责人和关闭 Gate。

不得把 Jest 中的 fake transport 测试标成真实网络 E2E，也不得把开发者工具 Functional 标成真机证据。

---

## 8. Gate A：内部微信测试版 Go/No-Go

只有以下条件全部满足，才允许生成内部测试里程碑：

- [ ] Release Decision Record 明确是内部、受邀、不可公开版本；
- [ ] 当前 Git SHA 的后端 SQLite、MySQL-only、前端、OpenAPI 和微信构建 CI 全部通过；
- [ ] 测试 HTTPS Origin、证书及 request/upload/download 合法域名在真机通过；
- [ ] 隔离 MySQL 0→当前、受支持升级、备份恢复和失败处置演练通过；
- [ ] FastAPI、Redis、readiness、图片持久化和管理员 bootstrap 通过；
- [ ] Guest、普通用户、ADMIN、SUPER_ADMIN、禁用用户最低纵向链路通过；
- [ ] iOS/Android、弱网/断网、前后台、上传与 unknown 矩阵有证据；
- [ ] Secret/生成物/依赖审计完成且所有微信可达高风险已有处置；
- [ ] 已知缺陷分级，没有数据破坏、越权、凭据泄漏或无法恢复的阻断缺陷；
- [ ] 体验版测试人员、反馈入口、测试数据、停用日期和环境清理责任明确；
- [ ] 版本仍显示内部测试属性，不提供公开入口或公开发布承诺。

Gate A 通过不代表微信登录、微信支付、安全强化、隐私审核或公开发布通过。

---

## 9. Gate B：对外公开微信小程序硬门槛

除 Gate A 全部项目外，公开发布至少要求：

### 9.1 身份与认证

- 普通用户微信登录完成；客户端只把 `wx.login` 的一次性 code 交给业务后端，AppSecret 和 `session_key` 不进入小程序；
- OpenID/UnionID 的使用边界、唯一约束、已有账号绑定、重复绑定、冲突、解绑、禁用和账号恢复规则冻结并测试；
- ADMIN/SUPER_ADMIN 是否继续账号密码登录经过独立威胁建模，不强迫高权限账号走不适合的自动注册流程；
- 登录/注册限流、refresh token 轮换、撤销、重放和旧 Token 兼容策略完成；
- 注册、登录、绑定等非幂等或身份敏感流程的 unknown 结果有安全恢复方式。

### 9.2 订单与支付

- Order create 具备服务端幂等键、严格请求身份和冲突语义；
- 若公开版本在线收款，必须实现微信支付服务端下单、客户端调起、支付通知验签、金额/商户/订单核对、通知幂等、主动查单、超时关闭、退款、对账和告警；
- 客户端支付成功不直接把 Order 标成 Paid，服务端以可信支付结果推进状态；
- 支付成功但客户端未知、通知重复/乱序/延迟、查单超时、退款失败和对账差异有可执行处置；
- 若公开版本不在线收款，必须移除或改写会让用户误认为已在线支付的交互，并冻结线下履约规则。

### 9.3 生产安全与运维

- 正式 HTTPS、DNS、证书续期、微信合法域名、MySQL、Redis、对象存储/CDN 和备份恢复通过；
- Secret 进入专用保管系统，具备最小权限、审计、轮换和泄漏响应；
- readiness/liveness、错误率、延迟、5xx、数据库/Redis、队列或回调、证书/Secret 到期、支付差异具备监控告警；
- 日志、指标和错误追踪不包含 Token、密码、AppSecret、支付密钥、完整个人信息或完整 Redis URL；
- 发布、回滚、停写、数据库前滚/恢复、事故联系人和观察窗口明确。

### 9.4 隐私、审核与用户权利

- 小程序类目、主体、服务内容和审核材料与真实功能一致；
- 隐私保护指引逐项对应实际收集、使用、存储、共享和删除的数据及调用的微信隐私接口；
- 用户同意、撤回、账号注销/删除请求、联系方式、数据保留和未成年人等适用事项经过合规 Review；
- 审核账号、测试说明、支付/非支付说明、管理员功能说明和后端可用窗口准备完成；
- RC 提审前再次复核微信开放文档、公众平台后台规则及适用法律/备案要求，不依赖本规划中的历史结论。

---

## 10. 风险优先级

| 优先级 | 风险 | 影响 | 最晚关闭 |
|--------|------|------|----------|
| P0 | CI 缺失，候选版本与历史测试证据不绑定 | 无法证明发布包就是已测试代码 | 9.2 |
| P0 | 生产 Origin/HTTPS/合法域名未冻结 | 真机无法请求或上传，不能形成体验版 | Gate A |
| P0 | 备份恢复和管理员 bootstrap 缺失 | 部署失败无法安全恢复或无法运营 | Gate A |
| P0 | 微信登录、公开身份绑定规则缺失 | 公众身份不可用或可能错误合并账号 | Gate B |
| P0 | 在线成交但无微信支付可信闭环 | 资金、订单状态和用户权益风险 | Gate B；在线收款时 |
| P0 | Order create 无服务端幂等 | 弱网重试可能产生重复订单/扣库存 | Gate B |
| P1 | refresh 不轮换、认证不限流 | Token 重放和撞库/滥用风险 | Gate B |
| P1 | 图片仍依赖应用本地目录 | 扩缩容、重建或故障时图片丢失/不一致 | Gate B；Gate A 先有持久化与备份 |
| P1 | health 不检查依赖 | 流量可能进入不可服务实例 | Gate A |
| P1 | Redis URL 日志本地已脱敏但尚缺 CI 证据 | 回归可能重新泄漏凭据 | Gate A |
| P1 | 管理分包随公开包发布的边界未决定 | 包体、审核面和攻击面增加 | Gate B |
| P2 | 发布元数据已收敛为微信 Gate A，但尚缺 CI/RC 复核 | 回归会导致发布范围和对外承诺混乱 | 9.2 |
| P0 | npm 10 项风险的微信/构建可达性未确认 | 不能证明当前微信产物不受直接组件或构建链风险影响 | 9.2 分析并在 Gate A 前处置可达高风险 |
| P2 | 经证据确认的 H5-only 风险仍可能存在 | 不阻断本版微信，但未来 H5 不能直接发布 | 本版记录 deferred；未来 H5 Phase 重新评估 |

---

## 11. Phase 9.1 完成定义

Phase 9.1 只有在以下条件满足后才能标记完成：

- 本版微信单平台和 Gate A→Gate B 顺序已写入路线图、测试策略与多端策略；
- 第 3.1 节每一项都有状态、证据和下一动作，没有“待确认但无负责人/关闭 Gate”的条目；
- 9.2–9.7 的输入、输出、依赖和退出条件已冻结；
- Environment Matrix、Secret Inventory、CI Gate Matrix、Runbook、验收矩阵、Risk Register 和 Go/No-Go 模板有明确存放位置；
- 明确当前生产 Origin、CI、备份恢复、readiness、管理员初始化是 Gate A 缺口；
- 明确微信登录、交易闭环、Order create 幂等、认证安全、生产监控和合规是 Gate B 缺口；
- 没有执行外部发布、持久迁移、Secret 写入、微信后台变更或商业平台绑定；
- 文档差异通过 Review，链接有效，未包含真实密码、Token、私钥、AppSecret 或连接串。

Phase 9.1 完成后，下一步是 **9.2 CI 与可重复构建**，不是直接实现微信支付，也不是直接上传正式版。

截至 2026-08-29，仓库级证据采集、八类交付物、文档联动、责任人映射和项目负责人 Review 均已完成，所有角色由 Yijie Shen 承担，Phase 9.1 状态为 **Complete**，当前进入 **9.2 CI 与可重复构建**。CI、演练、真机和外部环境缺口仍按后续阶段关闭；9.1 Complete 不等于 Gate A Ready，也不构成任何外部发布授权。

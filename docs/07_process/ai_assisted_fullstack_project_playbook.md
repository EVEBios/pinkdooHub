# AI 协作全栈项目规划与稳健交付手册

> **文档性质：** 跨项目方法论与新项目启动手册
>
> **适用对象：** 产品负责人、技术负责人、开发者、测试/运维人员，以及参与项目的 AI Agent
>
> **形成依据：** 对 pinkdooHub 需求、架构、代码分层、前后端测试、数据库迁移、CI、发布演练和 AI 协作方式的审计
>
> **审计日期：** 2026-09-08
>
> **重要边界：** 本文不替代 pinkdooHub 的业务规则、API、数据库设计、迁移流程或发布状态文档，也不表示当前候选已经获准部署或发布。

---

## 快速导航

1. [核心结论](#1-先给结论)
2. [pinkdooHub 推进方法复盘](#2-pinkdoohub-当前推进方法的复盘)
3. [新项目标准推进路线](#3-新全栈项目的标准推进路线)
4. [框架与架构选择](#4-框架与架构怎么选)
5. [服务器与基础设施选择](#5-服务器与基础设施怎么选)
6. [AI Ready 输入包](#6-开始项目前应给-ai-准备什么)
7. [Skills、脚本、CI 与 Connector](#7-skills脚本ciplugin-和-connector-怎么分工)
8. [可复用资产](#8-pinkdoohub-中哪些资产可以复用)
9. [效率、质量与稳健性](#9-如何同时保证效率质量和稳健性)
10. [数据、迁移、安全与发布底线](#10-数据迁移安全和发布的稳健底线)
11. [pinkdooHub 改进路线](#11-pinkdoohub-当前最值得提升的地方)
12. [新项目迭代计划](#12-一套可直接采用的新项目迭代计划)
13. [任务、ADR 与 Go/No-Go 模板](#13-可直接复制的任务模板)
14. [常见反模式](#14-常见反模式)
15. [最终决策检查表](#15-最终决策检查表)

---

## 1. 先给结论

pinkdooHub 最值得复用的不是 `FastAPI + Tortoise ORM + MySQL + Taro` 这组技术，而是下面这条推进链：

```text
产品问题与约束
  → 权威业务契约
  → 风险驱动的技术选型与 Spike
  → 可复现工程骨架
  → 一条最小全栈纵向链路
  → 按领域和风险扩展
  → 真实生产方言与外部边界验证
  → 可销毁发布演练
  → 持久环境验收
  → 人工 Go / No-Go
  → 小步上线、观察与复盘
```

如果重新创建一个不同类型的全栈项目，推荐遵守以下十条原则：

1. **先选问题，再选框架。** 框架和服务器是约束推导出的结果，不是项目起点。
2. **先明确权威事实源。** 需求、API、数据库、架构、实现、验证、部署状态必须各有归属。
3. **先做高风险 Spike。** 用最小实验验证多端、SSR、ORM 迁移、真实数据库、第三方 Provider、性能或部署未知项。
4. **先贯通一条纵向链路。** 不要先横向铺完所有 Model、API 或页面，再到最后才第一次集成。
5. **默认从模块化单体开始。** 缓存、队列、搜索、微服务和 Kubernetes 都由真实需求触发。
6. **开发环境快，发布门槛真。** 快速测试可以使用替身；类型、迁移、锁、并发和查询计划必须在生产方言上证明。
7. **把数据库迁移当独立交付物。** 迁移、回填、对账、备份、恢复和应用发布是相关但不同的动作。
8. **让脚本和 CI 证明事实。** 聊天记录、口头确认和“我记得通过了”不能替代绑定 SHA 和环境的证据。
9. **让 AI 加速理解与执行，不替人做不可逆决策。** 产品取舍、风险接受、生产写入和公开发布需要清晰的人类授权。
10. **完成定义是六件套：** `Contract + Code + Test + Documentation + Evidence + Cleanup`。

在没有相反约束时，一个务实的**候选起点**是：TypeScript 客户端 + 模块化单体后端 + 一个关系数据库事实源 + OpenAPI/Schema 契约 + 对象存储（有上传时）+ 容器化应用 + 托管数据库。Redis、Worker/Queue、搜索、微服务和 Kubernetes 只有在需求或实测证明需要时再增加。这个组合仍需经过第 4～5 节的评分和 Spike，不能直接当最终选型。

一句话概括 AI 的正确位置：

> AI 负责理解、推理、实现、验证和整理；仓库保存长期记忆；自动化验证事实；人负责产品取舍、风险接受和不可逆操作授权。

---

## 2. pinkdooHub 当前推进方法的复盘

### 2.1 项目实际上采用了四条相互衔接的主线

| 主线 | pinkdooHub 的做法 | 可泛化结论 |
|---|---|---|
| 工程底座 | 配置、日志、统一响应、异常处理、数据库、Redis、健康检查 | 业务前先建立最小可运行、可诊断、可测试底座 |
| 后端领域 | User/Auth/RBAC/Audit，再到 Product、Order、Inventory、Wallet、Reservation | 公共能力先行；领域内部契约先行、分层实现 |
| 客户端 | ADR、Taro 四端 Spike、正式骨架、认证、商品、订单、管理能力 | 技术风险先验证，正式开发按完整用户旅程切片 |
| 发布工程 | 基线审计、CI、一次性类生产演练、持久 Gate A、公开 Gate B | “代码可交付”“环境可恢复”“可以公开发布”是三个不同结论 |

后端模块已经形成相对稳定的执行顺序：

```text
现状审计与范围冻结
  → 领域语言 / Enum / 常量 / 异常
  → 输入输出 Schema
  → Model / 约束 / 索引 / 迁移设计
  → Repository
  → 纯业务 Validator
  → Service / 事务 / 锁 / 重试 / 幂等
  → Mapper / 输出白名单
  → API / 认证 / 权限
  → HTTP / 并发 / 真实数据库验证
  → Architecture / Security / Database / Testing / Documentation Review
```

Inventory 的 4.3.1–4.3.12 是这一模式最完整的实例；数据库迁移则有独立的生成、Review、演练和发布边界。相关依据见：

- [项目架构](../04_architecture/architecture.md)
- [编码规范](../05_development/coding_standards.md)
- [Code Review Checklist](code_review_checklist.md)
- [Database Migration Workflow](database_migration_workflow.md)
- [Frontend Architecture](../08_frontend/frontend_architecture.md)
- [Release Documents](../09_release/README.md)

### 2.2 这套方法最成功的部分

#### 事实来源有层级

pinkdooHub 明确区分：

| 要回答的问题 | 权威来源 |
|---|---|
| 产品应该怎样工作 | `docs/01_requirements/` 中已接受的业务规则 |
| HTTP 如何调用 | `docs/03_api/` 与 OpenAPI |
| 数据如何保存 | `docs/02_database/`、Model 与版本化迁移 |
| 为什么采用某个架构 | Architecture 与 ADR |
| 代码是否存在 | 当前 Git SHA 下的实际文件 |
| 行为是否验证 | 测试结果、CI Run、Artifact |
| 某环境是否已经升级 | 目标环境只读审计、迁移版本和部署记录 |
| 当前能否发布 | Release Evidence 与 Go/No-Go 记录 |

这能防止 AI 把 Draft 当成已接受设计、把仓库实现当成已部署能力，或把历史测试当成当前候选证据。

#### 高风险写入不是只靠单元测试

Order、Inventory、Wallet 等高一致性领域组合使用了：

- 顶层用例拥有事务；
- `SELECT ... FOR UPDATE`；
- 稳定锁顺序；
- 锁后重新校验；
- 数据库 UNIQUE 约束兜底幂等；
- 仅对明确瞬态错误重跑整个新事务；
- 故障注入与原子回滚测试；
- 真实 MySQL 并发、锁等待和 `EXPLAIN` 门禁。

项目曾由真实 MySQL 发现 SQLite 没暴露的 `IntEnum` 驱动编码问题。这是非常直接的证据：**快速测试环境通过，不能证明生产数据库的类型、迁移、锁和查询计划正确。**

#### 发布被做成证据链，而不是最后一条命令

当前流程明确区分：

```text
Designed
  → Implemented
  → Locally verified
  → CI verified
  → Production-like rehearsed
  → Persistently deployed
  → Enabled
  → UAT / Business accepted
  → Released
```

后一个状态不能被前一个状态替代。例如：

- 仓库里有代码，不等于 CI 通过；
- CI 通过，不等于对应 Artifact 已部署；
- 一次性容器验证通过，不等于持久数据库已经升级；
- 模拟器通过，不等于真机通过；
- Build 成功，不等于 Functional 成功；
- Feature Flag 的关闭路径存在，不等于真实 Provider 已接入；
- 历史 Run 通过，不等于当前 SHA 通过。

### 2.3 需要保留，但不应机械照搬的部分

以下是 pinkdooHub 的具体答案，不是全栈项目的通用答案：

- FastAPI、Tortoise ORM、Aerich、MySQL/SQLite、Redis；
- Taro、React、TypeScript 和微信/支付宝/抖音/H5 多端；
- API → Service → Repository → Model 的具体层次和“普通 Service 不互调”规则；
- 单服务器 Docker Compose Gate A；
- M0–M7、Phase 4.x/9.x、N1/N2 等阶段编号；
- Product、Kit、221 色、库存、钱包、预约和上海营业日历规则；
- 当前错误码、状态值、锁顺序和金额范围；
- 某一次 CI 数量、Run ID、候选 SHA 或环境阻断项。

应复用的是决策方法、边界意识和证据标准，而不是这些具体结论。

### 2.4 当前状态应如何安全理解

本次审计发现，根 `AGENTS.md`、README、changelog 和部分 Release 文档之间已有时效差异。2026-09-08 的真实 Gate A 演练先在 Runtime Secret 注入链问题上于 M3 DDL 前安全停止；修复候选随后完成完整 CI、匹配镜像、新 Backup/Restore，并已真实执行 M2→M7、钱包发布前准备、MARD 色板导入和候选韧性验证。当前仍未通过的是域名关联等待、外部 HTTPS、微信合法域名和真机 Release Candidate 验收，不能把内部升级完成误写成整体验收通过。部分较早摘要仍可能停留在第一次失败现场。

因此，本文不再尝试用一段长期文字定义实时发布状态。**当前项目仍是 No-Go；精确状态必须以最新 changelog、目标环境只读证据和 Release 决策记录共同确认。**这个实例本身说明了为什么下一步要减少状态复制，建立单一机器可读状态源。具体改进见第 11 节。

---

## 3. 新全栈项目的标准推进路线

### 3.1 不按“前端做完、后端做完”推进，而按 Gate 推进

建议让每个 Gate 都有四项内容：输入、产出、退出条件和证据。Gate 可以按项目大小合并，但不能用“应该差不多了”代替退出条件。

| Gate | 目标 | 核心产出 | 退出证据 |
|---|---|---|---|
| G0 产品与约束 | 决定做什么、为什么、不做什么 | Brief、用户旅程、领域词汇、规则、NFR、风险表 | 关键产品歧义关闭 |
| G1 技术决策 | 用约束选择技术，不凭偏好 | 候选矩阵、ADR、风险 Spike | 未知项有真实实验结论 |
| G2 可复现底座 | 干净环境能启动、测试、构建 | 仓库骨架、CI、配置、日志、健康检查、首迁移 | 新环境可按文档复现 |
| G3 最小纵向链路 | 证明全栈架构真实可用 | 一个 UI→API→DB→响应闭环 | 正常/错误/权限路径可验收 |
| G4 风险优先扩展 | 逐个交付业务能力 | 纵向功能切片、契约和测试 | 每个切片满足 DoD |
| G5 生产相似集成 | 证明方言、并发和外部边界 | 真实 DB、对象存储/队列/Provider Sandbox | 关键故障与恢复通过 |
| G6 可销毁发布演练 | 证明部署、迁移、备份、恢复 | 不可变 Artifact、演练报告、Evidence Manifest | 服务端同一 Digest，或客户端同一 SHA 的环境制品，完成演练并清理 |
| G7 持久验收环境 | 证明真实起点可升级并可长期验收 | 备份、迁移、监控、E2E/真机 | 业务方验收；高风险能力仍受控 |
| G8 生产 Go/No-Go | 决定是否开放真实流量 | 安全/合规/容量/回滚/值守记录 | 人工授权，全部阻断关闭或获批例外 |
| G9 上线与运营 | 小步启用并持续证明可靠性 | Canary、指标、告警、复盘、恢复演练 | SLO 和业务指标稳定 |

### 3.2 G0：产品与约束

编码前最少回答：

- 谁是目标用户？他们现在怎样解决问题？
- 最高价值的三个用户旅程是什么？
- MVP 明确不做什么？
- 哪些规则关系到钱、库存、权限、隐私、法律或不可逆数据？
- 是 Web、内容站、后台、App、小程序、桌面端还是多端？
- 是否需要 SEO、SSR、离线、实时协作、文件上传或推送？
- 支持哪些语言、Locale、币种、时区、日历、浏览器和设备？可访问性目标是什么？
- 是否多租户？租户隔离、数据分类、保留、归档、法律删除和同意管理怎样处理？
- 目标地区、数据驻留、备案、域名、证书和平台审核约束是什么？
- 峰值流量、数据量、延迟、可用性、RPO、RTO 的初始假设是什么？
- 预算、交付期限和实际运维人力是多少？
- 哪些第三方账号、资质、Sandbox 或真机条件尚未取得？

G0 的产物不需要很长，但必须可验证。建议至少有：

```text
PRODUCT_BRIEF.md
GLOSSARY.md
USER_JOURNEYS.md
NON_FUNCTIONAL_REQUIREMENTS.md
RISK_REGISTER.md
```

### 3.3 G1：技术决策与风险 Spike

技术选型应先淘汰违反硬约束的方案，再给剩余候选打分。可使用以下默认权重，具体项目允许调整：

| 维度 | 默认权重 | 问题 |
|---|---:|---|
| 业务匹配 | 25 | 能否自然表达核心场景、端形态和一致性要求？ |
| 团队能力 | 20 | 团队能否维护、排障和招聘？ |
| 迁移与生态 | 15 | 数据库迁移、测试、监控、安全生态是否成熟？ |
| 部署与运维 | 15 | 能否在目标平台稳定运行，团队能否值守？ |
| 质量与安全 | 10 | 类型、验证、权限、依赖治理和审计能力如何？ |
| 性能与容量 | 10 | 在已知负载模型下是否足够？ |
| 可移植性 | 5 | 退出云平台、框架或 Provider 的成本如何？ |

计算方式：

```text
候选总分 = Σ（单项 1～5 分 × 权重）
```

总分不是自动决策器。任何违反合规、数据安全、交付期限或团队运维上限的方案，都应先按硬约束淘汰。

每项长期技术决策都应形成 ADR：

```text
Context
Decision drivers
Options
Decision
Why
Rejected alternatives
Consequences
Validation plan
Revisit triggers
```

Spike 不是搭一个空 Hello World。它必须覆盖最可能失败的那一段，例如：

- 前端框架：真实登录、路由、状态恢复、生产构建和目标端运行；
- ORM/数据库：非空增量迁移、Decimal/Enum/UTC、复合唯一、FK、行锁、回滚和批量查询；
- SSR：首屏、缓存、鉴权、动态内容和部署适配；
- 实时协作：断线重连、顺序、冲突和背压；
- 外部 Provider：签名、超时、重放、结果未知和 Sandbox；
- 文件存储：上传、校验、补偿删除、私有访问和 CDN；
- 部署平台：Secret、迁移 Job、健康检查、日志、扩缩容和回滚。

### 3.4 G2：可复现工程底座

业务功能扩展前至少建立：

- 运行时、包管理器和锁文件；
- `.env.example` 和结构化配置校验；
- Secret 忽略与注入规则；
- Format、Lint、Typecheck、Unit/Integration Test；
- 统一错误和结构化日志；
- request/trace ID；
- liveness 与 readiness；
- 首个数据库迁移，而不是运行时隐式建表；
- 一键本地启动；
- 一条干净 checkout 的 CI；
- 基础依赖和 Secret 扫描；
- ADR、任务 Brief 和 Review 模板。

退出条件不是“开发者电脑能跑”，而是另一台干净环境可以只依赖文档和锁定版本复现。

### 3.5 G3：最小纵向链路

选择一个价值高但范围窄的用户旅程，完整贯通：

```text
页面 / 客户端
  → API 契约
  → 输入校验
  → 认证与权限
  → 用例 / 事务
  → 持久化
  → 输出白名单
  → 前端状态与错误呈现
  → 日志、指标和追踪
  → 自动化测试
  → 部署与回滚
```

例如，项目是 SaaS，不要先建十张表和二十个空路由；可以先交付“管理员邀请一个成员，成员接受后能看到一个受权限保护的资源”。项目是内容站，可以先交付“编辑发布一篇文章，访客从 SEO 页面读取”。项目是电商，可以先交付“浏览一个商品并创建一笔未支付订单”，但先关闭真实支付。

### 3.6 G4：按风险和依赖扩展，不按目录扩展

推荐优先级：

1. 会改变核心数据模型或事务边界的能力；
2. 最难验证、最依赖外部条件的能力；
3. 身份、权限、隐私和审计边界；
4. 主用户旅程；
5. 管理与运营能力；
6. 体验优化和低风险辅助功能。

每个切片仍走“小型 G0～G4”：冻结规则、同步契约、实现、验证、Review 和记录证据。

### 3.7 G5～G9：把发布风险逐层变成证据

#### 生产相似集成

- 使用当前精确目标数据库版本，并声明受支持版本范围；同时冻结 driver、字符集/collation、时区、隔离级别、SQL mode 或 extension；
- 空库迁移与至少一个真实历史起点升级；
- 锁、死锁、超时、幂等和整事务重试；
- 关键查询 `EXPLAIN`；
- Redis、对象存储、队列和 Provider 的失败语义；
- Backfill、Reconcile 和 Feature Flag 关闭路径。
- 在代表性数据量下验证 load、soak、过载保护和告警送达。

#### 可销毁演练

- 只使用不可变制品；
- 应用启动与迁移分离；
- non-root、内部网络、唯一公开入口；
- TLS、健康检查、优雅关闭；
- 备份和独立恢复；
- 数据库/缓存/应用故障与恢复；
- 日志脱敏；
- 完整资源清理和复核。

#### 持久验收环境（G7）

- 只读确认真实起点，不能凭上次记录猜测；
- 为本次变更创建新鲜备份并独立恢复；
- 迁移、回填、对账、启用分开授权；
- 使用生产配置语义和合成数据或经批准的脱敏数据；
- 运行真实浏览器/设备 E2E、代表性负载、soak、过载和告警送达测试；
- 高风险外部能力继续由 Feature Flag 关闭；
- 持久验收通过不自动授权生产或公开流量。

#### 生产 Go/No-Go（G8）

- 域名、证书、合规、外部 Provider 和平台审核按适用范围逐项验收；
- 所有阻断门槛和 P0 风险必须关闭；P1 只有在更高级审批、补偿控制、影响范围、Owner 和到期日完整时才可例外；
- 明确制品身份、精确环境、授权动作、回滚/前滚阈值、发布窗口、观察窗口和事故联系人；
- 明确容量、SLO、告警和值守能够支持计划流量；
- 小流量启用，观察技术指标和业务不变量。

---

## 4. 框架与架构怎么选

### 4.1 先准备选择输入

不要只问 AI“React 还是 Vue”“FastAPI 还是 NestJS”。至少给出：

- 团队熟悉的语言、框架和部署方式；
- 产品端形态与支持矩阵；
- SEO/SSR、离线、实时、媒体和推送要求；
- 核心状态机、事务、并发、幂等和一致性要求；
- 数据规模、峰值 RPS、突发流量和未来一年增长假设；
- 延迟、可用性、RPO、RTO；
- 地区、合规、数据驻留和平台限制；
- 预算、上线时间、运维人数和值守能力；
- 已有系统、数据迁移和组织技术标准；
- 未来最可能发生变化的模块。

要求 AI 输出两到三个候选、评分、主要风险、退出成本、推荐项、待验证未知项和 ADR。所有可能变化的版本、价格、云服务能力、平台规则和支持周期，都应在决策当天查官方来源并记录日期。

### 4.2 前端候选矩阵

| 项目类型 | 优先考察 | 为什么 | 需要 Spike 的风险 |
|---|---|---|---|
| 内容、营销、文档、SEO | Astro、Next.js、Nuxt 或成熟 CMS 前台 | 静态生成/SSR、路由与内容生态 | 缓存失效、动态鉴权、编辑预览、部署平台 |
| SaaS、管理后台、复杂表单 | React/Next、Vue/Nuxt + TypeScript | 组件生态、类型契约、复杂交互 | 状态管理、表格/表单、权限、E2E、包体 |
| 微信/多小程序/H5 | Taro、uni-app 或平台原生 | 是否真正需要一套代码多端 | 目标端差异、包体、插件、支付、真机 |
| iOS/Android App | Flutter、React Native 或原生 | 交付速度与平台能力取舍 | 原生桥接、后台任务、推送、商店审核 |
| 简单内部工具 | 服务端模板、Admin 框架或低代码 | 降低前端工程成本 | 权限、审计、扩展边界和平台锁定 |
| 实时协作/画布 | React/Vue + 专项实时/渲染技术 | 核心问题不是普通 CRUD | 冲突模型、断线重连、渲染性能、协议 |

Next.js 官方支持 Node.js Server、Docker、静态导出和平台适配器等部署方式；因此“使用 Next.js”并不自动决定服务器形态，仍需结合 SSR 与运行时能力选择。[Next.js deployment](https://nextjs.org/docs/app/getting-started/deploying)

### 4.3 后端候选矩阵

| 场景 | 优先考察 | 优势 | 主要代价/验证项 |
|---|---|---|---|
| Python 团队、API/AI/数据集成 | FastAPI + 成熟 ORM/迁移工具 | 类型驱动、OpenAPI、异步生态 | ORM 迁移、连接池、同步/异步边界 |
| 后台和 CRUD 占比高 | Django + Django ORM/Admin | 完整内建能力、管理后台和迁移生态 | 异步需求、API 组织、复杂领域边界 |
| 全栈 TypeScript 团队 | NestJS + 成熟 ORM/Query Builder | 模块、DI、测试和前后端语言统一 | 运行时验证、ORM 迁移、Node 资源模型 |
| JVM 企业集成 | Spring Boot/Kotlin | 生态、治理、可观测和组织支持 | 启动/资源成本、工程复杂度 |
| 已证明的吞吐或资源约束 | Go + 明确的数据访问层 | 简洁部署、并发和资源效率 | 业务表达、迁移生态、团队熟悉度 |
| 团队已有成熟资产 | Rails、Laravel 等 | 组织经验往往比理论比较更重要 | 生命周期、依赖和生产运维能力 |

FastAPI 官方强调 OpenAPI、类型校验、依赖注入和自动交互文档；Django 官方教程展示了 ORM、迁移和自动管理后台；NestJS 以模块化、可测试、可维护的服务端架构为核心；Spring Boot 提供生产特性；Go 标准库提供连接池语义。这些是候选能力，不是对所有项目的自动推荐。[FastAPI features](https://fastapi.tiangolo.com/features/) · [Django tutorial](https://docs.djangoproject.com/en/5.2/intro/tutorial01/) · [NestJS introduction](https://docs.nestjs.com/introduction) · [Spring Boot](https://docs.spring.io/spring-boot/) · [Go database access](https://go.dev/doc/database/)

### 4.4 默认从模块化单体开始

大多数新项目的稳健默认值是：

```text
一个主要可部署后端
  + 清晰领域模块
  + 一个关系数据库事实源
  + 契约化 API
  + 一个或多个客户端
```

“模块化单体”描述的是部署和模块边界，不要求所有代码必须在一个仓库。Monorepo 或 Polyrepo 应按客户端数量、权限隔离、团队所有权、版本联动和发布节奏另做 ADR；不要把仓库拓扑误当成服务边界。

渐进演化顺序：

```text
模块化单体
  → 有可靠异步需求时增加独立 Worker
  → 有明确查询需求时增加缓存或搜索
  → 只有独立扩缩容、发布节奏、团队所有权或安全边界被证明时拆服务
```

每增加一个组件，都必须同时回答：

- 谁维护？
- 如何本地开发和 CI？
- 如何监控和告警？
- 如何备份和恢复？
- 如何升级和修补漏洞？
- 故障时业务是 fail-open、fail-closed 还是降级？
- 如何退出或迁移？

如果这些问题答不出来，当前阶段通常不应增加这个组件。

### 4.5 数据库、缓存、队列和存储

#### 关系数据库

订单、账户、库存、权限、预约等事务型领域，默认优先 PostgreSQL 或 MySQL。选择依据应是团队经验、托管能力、现有系统、扩展和迁移生态，而不是网络流行度。

| 数据系统 | 适合 | 不应承担 |
|---|---|---|
| PostgreSQL/MySQL | 强事务、关系、约束、通用业务事实 | 不经设计地承担全文搜索、海量分析或文件存储 |
| SQLite | 嵌入式、本地工具、单机和低并发写 | 高并发多实例交易系统的生产替代品 |
| 文档数据库 | 文档聚合天然、访问模式稳定且弱关系 | 为逃避 Schema 设计而保存强关系/资金事实 |
| 搜索引擎 | 全文检索、相关性、聚合查询 | 订单、账户、权限的唯一事实源 |
| 分析仓库/湖 | 报表、分析、离线训练 | 在线交易主写路径 |

一个项目可以有多种存储，但每类事实必须有唯一权威源，并设计同步延迟、重建和不一致处理。早期项目通常先用一个关系数据库完成正确模型，再让搜索、缓存和分析成为可重建投影。

SQLite 适合本地工具、嵌入式应用、单机数据和低并发写场景；其同一数据库文件同一时刻只有一个写事务，因此不能替代真实客户端/服务器数据库的并发和迁移门禁。[SQLite: Appropriate Uses](https://www.sqlite.org/whentouse.html)

如果开发使用 SQLite、生产使用 MySQL/PostgreSQL，应在项目初期加入真实生产方言 CI，而不是发布前再补。新 Python 项目还应以同一组真实用例 Spike 比较 ORM/迁移组合：

- 复合唯一、外键与删除策略；
- Decimal、Enum、JSON 和 UTC；
- 行锁、超时、死锁与回滚；
- 批量读写与 N+1；
- 空库迁移和非空历史升级；
- Forward repair 与 downgrade；
- 关键查询计划。

#### Redis

只有出现具体需求时再引入：Session/撤销、限流、短期缓存、协调或队列。Redis 不应成为资金、订单和库存的唯一事实源。

必须逐项定义故障语义：

- 普通缓存只有在数据库回源容量、超时预算、请求合并/防击穿、限流和负载削减都允许时才可 fail-open 或绕过，否则缓存故障会放大成数据库故障；
- 身份撤销、认证限流或安全协调通常倾向 fail-closed，但必须由威胁模型明确其可用性代价、应急入口和恢复方式；
- 业务事实先落关系数据库，再异步刷新缓存；
- Key 生命周期、容量、淘汰和恢复后的行为必须可测。

#### 队列与异步任务

| 方案 | 适用情况 | 限制 |
|---|---|---|
| 进程内 Background Task | 很短、可丢失、非关键任务 | 重启可丢，不可冒充可靠投递 |
| cron/平台定时 Job | 清理、日报、低频维护 | 实时性和并发有限 |
| 数据库 Outbox + Worker | 必须与业务事务原子入队，低中吞吐 | 需 claim、lease、扫描索引和 Worker |
| Redis-backed Job Queue（RQ/BullMQ/Celery-with-Redis 等） | 常规后台任务且已有 Redis | 需明确 Broker/Result Backend、持久性、重试、死信和重复 |
| RabbitMQ/托管任务队列 | 需要 ack、路由、延迟和背压 | 增加关键基础设施 |
| Kafka/Pulsar | 高吞吐事件流、多消费者、重放 | 运维和模型复杂，不是普通任务队列默认值 |

可靠分布式任务通常都要设计幂等消费、最大重试、退避+jitter、dead 状态、积压/最老任务指标和外部调用“结果未知”状态；具体并发机制不能混用：数据库轮询/租约认领关注 lease 与 fencing，相应 Broker 关注 ack、visibility timeout 和 redelivery。Outbox 若继续发布到 Broker，还需要可靠 Relay，不能重新形成数据库与 Broker 双写。跨数据库和外部 Provider 不应宣称 exactly-once；应明确接受并治理 at-most-once 或 at-least-once。

#### 文件与对象存储

推荐边界：

- 本地开发可用本地目录；
- 内部单机环境可用明确备份的持久卷；
- 多实例或生产上传通常使用对象存储；只有公共且可缓存的内容才配 CDN，私有文件使用服务端鉴权或短时签名 URL；
- 业务层依赖存储接口，不依赖某个 SDK；
- 服务端生成唯一 key，不信任客户端文件名；
- 同时校验大小、声明 MIME、扩展和内容签名；
- 数据库保存稳定 object key 和元数据，不保存会过期的签名 URL；
- 存储成功但数据库失败时执行 best-effort 补偿删除；失败时记录 orphan、重试并定期 reconcile；
- 逻辑删除与物理清理分开；
- 清理任务默认 dry-run，保护仍被有效记录引用的文件。
- 用户内容按风险增加隔离区、恶意内容/压缩炸弹检查、杀毒或人工审核。

#### API 契约

REST 项目通常可以 OpenAPI 作为前后端共同契约，并用生成类型和 CI 漂移检查减少手工复制；生成类型仍不能替代运行时边界校验。事件驱动系统应补 AsyncAPI 或等价事件 Schema；GraphQL 则应以 Schema 和兼容策略为权威。[OpenAPI Specification](https://spec.openapis.org/oas/latest.html)

| 接口形态 | 优先场景 | 必须治理 |
|---|---|---|
| REST + OpenAPI | 普通 Web/App、资源与命令式业务 | 版本、错误、分页、幂等、生成物漂移 |
| GraphQL | 多种客户端需要灵活读取复杂关系图 | 查询成本、N+1、授权、Schema 演化、缓存 |
| gRPC/RPC | 受控内部服务、强类型低延迟调用 | 兼容、超时、重试、网关和调试体验 |
| WebSocket/SSE | 实时状态、协作、流式结果 | 认证续期、顺序、背压、重连和降级 |
| Event/AsyncAPI | 异步集成和多消费者事件 | 幂等、顺序、Schema 版本、重放和死信 |

认证也应单独决策：消费者登录、企业 SSO/OIDC、多租户、管理员高权限、会话撤销和合规需求复杂时，优先评估成熟托管身份服务；若选择自建，必须把密码、MFA、恢复、Session/Token 轮换、限流、审计和密钥轮换纳入长期运维成本。

### 4.6 按项目类型给出的起步组合

以下是“开始验证的候选”，不是无需论证的标准答案：

| 项目类型 | 候选起步组合 | 部署起点 | 最先验证 |
|---|---|---|---|
| 内容/品牌/文档站 | Astro/Next/Nuxt + Headless CMS 或少量后端 | 静态托管/CDN | SEO、编辑预览、缓存、表单与分析 |
| 内部管理系统 | React/Vue 或服务端模板 + Django/Nest/FastAPI + PostgreSQL/MySQL | PaaS 或单 VM Compose | RBAC、审计、导入导出、备份恢复 |
| 交易型 SaaS/电商 | TS 前端 + 模块化单体 + 关系 DB + 对象存储 | 托管容器 + 托管 DB | 事务、幂等、支付/库存、非空迁移 |
| 小程序/多端业务 | Taro/uni-app/原生 + API 后端 + 关系 DB | 托管容器 + 托管数据服务 | 真机、包体、登录、域名、平台 Provider |
| 移动 App | Flutter/RN/原生 + API/BFF + 关系 DB | 托管容器/Serverless | 原生桥接、推送、离线、商店审核 |
| 实时协作 | Web/App + WebSocket/Realtime 层 + 关系 DB | 多实例 + 托管状态服务 | 冲突、顺序、重连、扩散和背压 |
| AI/数据产品 | Web + API 编排层 + Worker/队列 + 对象存储 | 独立 Web/Worker、托管队列/DB | 成本、超时、评测、模型降级、数据治理 |

---

## 5. 服务器与基础设施怎么选

### 5.1 先选运行模型，再选 CPU/内存

| 模型 | 适合阶段 | 优点 | 主要限制 |
|---|---|---|---|
| 静态托管/CDN | 内容站、纯前端 | 低运维、全球分发 | 不承载有状态后端 |
| PaaS/Serverless + 托管数据 | 小团队、公开 MVP、流量波动 | 上线快、补丁和弹性负担低 | 平台限制、冷启动、成本随量变化 |
| 单 VM + Docker Compose + Nginx | 内部测试、邀请环境、低流量且可接受停机 | 直观、成本可控、容易演练 | 单故障域，不是高可用 |
| 多 App + LB + 托管 DB/Redis/对象存储 | 正式中小型生产 | 无状态 App 可替换和扩容 | 成本与部署治理增加 |
| Kubernetes | 多服务、多团队、复杂弹性/治理 | 调度、滚动发布和平台能力强 | 学习、维护和排障成本最高 |

Docker 官方给出了用额外 Compose 文件覆盖生产配置的方式；这适合受控单机部署，但仍需自己承担主机、状态服务和备份恢复责任。[Docker Compose in production](https://docs.docker.com/compose/how-tos/production/)

Kubernetes 官方生产环境文档要求同时规划可用性、规模、安全和控制面等问题。因此，Kubernetes 应是被组织和负载证明的选择，而不是“项目以后可能变大”的预防性选择。[Production environment](https://kubernetes.io/docs/setup/production-environment/)

Cloud Run、Azure Container Apps 等托管容器平台可以减少集群运维，并提供按请求/事件扩缩等能力；是否适用仍取决于长连接、最大请求时长、临时文件系统、后台任务生命周期、最大实例扇出与数据库连接风暴、VPC/跨区流量、scale-to-zero、冷启动、合规和成本。[Cloud Run autoscaling](https://docs.cloud.google.com/run/docs/about-instance-autoscaling) · [Azure Container Apps overview](https://learn.microsoft.com/en-us/azure/container-apps/overview)

### 5.2 云厂商和区域选择表

不要只比较一台 VM 的月费。至少比较：

| 维度 | 需要确认 |
|---|---|
| 用户与区域 | 用户时延、数据驻留、跨境和可用区 |
| 托管能力 | DB、Redis、对象存储、CDN、队列、Secret、日志和告警 |
| 可靠性 | SLA、备份、时间点恢复、跨故障域、恢复演练 |
| 合规与渠道 | 备案、域名、证书、隐私、应用商店/小程序平台限制 |
| 成本 | 计算、数据库、IOPS、快照、流量、日志、监控和技术支持 |
| 安全 | IAM、最小权限、KMS、审计、网络隔离和漏洞治理 |
| 自动化 | IaC、API、制品仓库、环境审批和回滚 |
| 退出成本 | 数据导出、兼容服务、域名/CDN 切换和迁移时间 |

自建单机的现金账单可能较低，但补丁、备份、恢复、值守和事故成本必须计入总成本。

### 5.3 容量估算与起测规格

先用实际请求 Benchmark 建模：

```text
稳态平均 in-flight 请求数
≈ 稳态平均 RPS × 平均响应秒数

CPU 核心数
≈ 峰值 RPS × 单请求 CPU 秒数 ÷ 目标 CPU 利用率

应用内存
≈ 进程基线
 + 并发 × 单请求工作集
 + 连接池 / 缓存 / 运行时开销
 + 安全余量

数据库总连接
= App 实例数 × 每实例进程数 ×（pool size + max overflow）
 + Worker 连接
 + 迁移 / 运维预留连接
```

第一条是 Little’s Law 的稳态近似，不是用 `峰值 RPS × p95` 代替实测并发。突发排队、WebSocket/SSE、LLM 流式响应和长任务要单独建模。数据库连接预算必须低于实例可用上限，并为管理和恢复保留连接；Serverless 还要按最大实例数估算扇出，并按需使用连接代理或受控池化。

数据库还要单独评估热数据、索引、临时表、排序、binlog/WAL、迁移额外空间、备份暂存、未来增长和 IOPS。

下表只能作为压测起点，不能当生产容量承诺：

| 场景 | 起测点 |
|---|---|
| 静态站 | CDN/静态托管，无常驻 App VM |
| 开发或短期 Preview | 1–2 vCPU、2–4 GiB |
| App/DB/Redis 同机的低流量内部环境 | 2 vCPU、4 GiB 起测 |
| 小型公开服务、数据库已托管 | 两个 2 vCPU、2–4 GiB App 实例起测 |
| CPU/媒体/AI 任务 | 与 Web App 分离的独立 Worker 起测 |
| 数据库 | 按热数据、连接、IOPS、恢复和增长单独测试 |

最终规格由典型负载、峰值压力、长时间 soak、锁竞争、大数据迁移、依赖故障和备份窗口决定。容量告警至少观察 CPU、内存、磁盘/IOPS、连接池等待、数据库延迟、队列积压、错误率、p95/p99 和核心业务对账结果。

### 5.4 建议的生产拓扑演化

```text
阶段 A：开发 / Preview
客户端 → 单 App → 单关系数据库

阶段 B：内部持久环境
客户端 → Edge/Nginx → App
                        ├─ DB
                        ├─ Redis（按需）
                        └─ 持久文件卷（仅受控环境）

阶段 C：公开中小型生产
客户端 → Edge/TLS（按需 CDN/WAF）→ LB → 无状态 App Replica
                                          ├─ 具备明确 HA/PITR 的托管关系数据库
                                          ├─ 托管 Redis（按需）
                                          ├─ 对象存储/CDN
                                          └─ 独立 Worker/Queue（按需）

阶段 D：规模或组织证明需要
多服务 / 多 Worker / 专项存储 / 平台编排
```

Replica 数量和故障域由 SLO 决定。两个实例只有分布在合适的独立故障域，并且状态服务也具备对应 HA/PITR 时才有高可用意义；如果业务明确接受停机，单实例生产也可以是一项有记录的风险选择，而不是伪装成高可用。

公开生产的最低治理项通常包括：

- 容器使用不可变 Digest，或由 Registry 强制不可变的完整 Git SHA Tag，不用可覆盖的 `latest`；
- 后端及支持 runtime config 的制品构建一次、按 Digest 逐环境晋级；若 SPA/Taro/原生客户端把 Origin、AppID、签名等编入产物，则从同一干净 SHA 分环境构建，并分别绑定 checksum/manifest，禁止修改编译后产物；
- 迁移 Job 与 App 启动分离；
- App 不持有数据库 Root 权限；
- 数据库、缓存和 App 仅在内部网络；
- non-root、`no-new-privileges`、只读根文件系统和受限临时目录；
- liveness/readiness 分离；
- 使用 Secret Manager 或等价系统治理 Secret 版本、审计、轮换和撤销；容器内只读文件只是投递形式，不把长期宿主明文文件当完整 Secret 治理；
- 集中日志、指标、Trace、错误追踪和告警；
- 自动备份、独立恢复演练和跨故障域副本；
- 发布前后版本对比、回滚/前滚和观察窗口。

备份不能只证明“文件生成成功”，还要在独立目标中恢复并校验完整性。AWS Well-Architected 也明确建议定期执行恢复测试以验证备份过程和数据完整性。[Testing data recovery](https://docs.aws.amazon.com/wellarchitected/latest/reliability-pillar/back-up-data.html)

### 5.5 可观测性与 SLO

至少为以下层面准备指标和告警：

| 层面 | 观测内容 |
|---|---|
| 请求 | 吞吐、延迟、错误率、状态码、版本、request/trace ID |
| 数据库 | 连接池等待、慢查询、锁等待、死锁、复制延迟、容量 |
| Redis/缓存 | 命中率、延迟、错误、内存、淘汰、连接 |
| Worker/队列 | 积压、最老任务年龄、处理延迟、重试、dead 数量 |
| 外部 Provider | 成功、明确失败、超时/结果未知、限流、回调延迟 |
| 业务不变量 | 资金对账、库存差异、订单状态矛盾、授权异常 |
| 发布 | 新旧版本错误率/延迟差异、回滚阈值、Flag 状态 |

OpenTelemetry 将 traces、metrics、logs 和 baggage 作为主要遥测信号，可作为跨语言观测标准的候选；是否使用其 Collector 和具体后端仍需单独 ADR。[OpenTelemetry signals](https://opentelemetry.io/docs/concepts/signals/)

---

## 6. 开始项目前，应给 AI 准备什么

### 6.1 最小 AI Ready 输入包

| 输入 | 至少包含 | AI 用它做什么 |
|---|---|---|
| 项目章程 | 问题、目标用户、价值、非目标、成功指标、预算、期限 | 判断什么应该做，防止技术范围漂移 |
| 领域词汇 | 实体、术语、状态、易混概念 | 让产品、前端、后端和数据库使用同一语言 |
| 用户/权限模型 | 用户类型、角色、资源归属、允许/禁止操作 | 设计认证、授权、UI 守卫和审计 |
| 核心用户旅程 | 正常、失败、撤销、管理员路径 | 选择第一个纵向切片和验收场景 |
| 业务规则 | 状态机、金额/数量/时间边界、唯一性、并发、幂等 | 避免 AI 自行发明关键语义 |
| 非功能需求 | 流量、延迟、可用性、RPO/RTO、安全、合规、地区、SEO、多端 | 推导架构、数据库和服务器 |
| 体验兼容基线 | 可访问性目标、最低浏览器/设备、渐进降级、i18n、Locale、币种、时区/日历 | 让设计、数据和测试覆盖真实用户环境 |
| 数据治理 | 数据分类、最小化、同意、保留/归档/删除、多租户隔离 | 决定 Schema、权限、审计和合规流程 |
| 架构边界 | 模块、依赖方向、事务所有者、外部端口 | 防止跨层查询、循环依赖和分散事务 |
| 接口契约 | OpenAPI/GraphQL/AsyncAPI、错误、分页、版本、幂等 | 前后端独立开发和自动检查漂移 |
| 数据设计 | ER、字段、约束、索引、生命周期、迁移/回填 | 把数据不变量从 ORM 默认中显式化 |
| 安全基线 | 威胁、认证、授权、Secret、PII、日志、上传、Webhook | 在实现前建立信任边界 |
| 环境矩阵 | local/test/CI/staging/prod 的差异和版本 | 防止把本地通过误作生产证据 |
| 命令清单 | 安装、启动、定向/完整测试、Lint、构建、迁移预览 | 让 AI 可重复执行，不猜命令 |
| Definition of Done | 契约、代码、测试、文档、证据、清理 | 约束完成声明 |
| 当前状态台账 | 能力、SHA、环境、证据、Flag、阻断项 | 区分 Planned/Implemented/Verified/Deployed |

如果这些信息尚不完整，不需要先写几十页文档。可以先让 AI 以只读方式列出已知、假设、冲突和必须由人决定的问题，再把答案写入权威文件。

### 6.2 按需补充的设计与外部输入

进入相关阶段前再提供：

- Figma、设计 Token、组件状态、断点和交互说明；
- 品牌规范、字体授权、图标/图片来源；
- 脱敏样例数据和确定性 Seed/Verifier；
- 第三方官方文档、API 版本、Sandbox、错误码、Webhook 契约；
- 支付、通知、地图、搜索、OAuth、AI 等外部服务的失败和重放语义；
- 浏览器、设备、小程序/App 支持矩阵；
- WCAG 等可访问性目标、键盘/读屏/对比度验收和渐进降级规则；
- 支持语言、Locale、币种、时区、日历和内容翻译流程；
- 产品分析事件、用户同意、数据最小化、保留/归档/法律删除和多租户隔离；
- 性能预算和基准数据；
- 隐私、保留、导出和删除要求；
- 备份恢复、告警、值守和事故 Runbook；
- 平台审核、证书、域名、备案或商户资质清单。

### 6.3 不应交给 AI 的内容

- 明文密钥、密码、Token、私钥、含私钥的证书包、客户端凭据和其他 Secret；
- 未脱敏的生产数据库 Dump 或真实个人信息；
- 可能包含凭据的完整日志；
- 无日期、无版本、无权威级别的第三方规则；
- 大量未索引的历史聊天记录；
- 同一规则的多份冲突副本；
- 把规划写成“已完成”的路线图；
- 无法绑定 Git SHA、CI Run、Artifact 和环境的测试结论；
- 对生产、云账号或外部系统的无限制凭据和写权限。

测试凭据应通过受控环境变量、Secret 文件、Secret Manager 或权限受限的 Connector 提供。AI 需要知道 Secret 的**名称、用途、来源和轮换方式**，通常不需要在上下文里看到 Secret 的值。Secret 文件应位于仓库外或明确 Git Ignore 的受控目录，使用最小文件权限（例如仅 Owner 可读），只暴露给真正需要它的进程，并禁止在工具输出、测试证据和最终答复中回显。公共 CA 证书或不含私钥的服务器证书不属于 Secret，但仍应验证来源和有效期。

### 6.4 推荐的权威文档结构

目录不必一开始全部创建；只创建当前阶段会真正维护的文件。关键是内容分工稳定：

```text
project/
├── AGENTS.md
├── README.md
├── .env.example
├── .tool-versions                 # 或语言专用版本文件
├── .agents/
│   └── skills/                    # 项目级、按需加载的重复工作流
├── docs/
│   ├── README.md                  # 总导航
│   ├── product/
│   │   ├── vision.md
│   │   ├── glossary.md
│   │   └── journeys.md
│   ├── requirements/
│   │   └── <domain>.md
│   ├── architecture/
│   │   ├── overview.md
│   │   └── adr/
│   ├── contracts/
│   │   ├── openapi.yaml
│   │   └── events.yaml
│   ├── database/
│   │   ├── schema.md
│   │   ├── schema.dbml
│   │   └── migration-workflow.md
│   ├── security/
│   │   ├── threat-model.md
│   │   ├── data-classification.md
│   │   └── secrets.md
│   ├── testing/
│   │   ├── strategy.md
│   │   └── acceptance-matrix.md
│   ├── operations/
│   │   ├── environments.md
│   │   ├── observability.md
│   │   ├── backup-restore.md
│   │   └── incident-runbook.md
│   ├── release/
│   │   ├── gate-matrix.md
│   │   ├── go-no-go.md
│   │   └── evidence/
│   └── ai/
│       ├── context-index.md
│       ├── current-state.yml
│       ├── task-brief-template.md
│       └── handoff-template.md
├── scripts/
│   ├── check-contract-drift
│   ├── verify-migration
│   ├── seed-synthetic-data
│   ├── verify-seed
│   └── build-release-manifest
└── .github/workflows/
    ├── ci.yml
    ├── security.yml
    └── release-candidate.yml
```

### 6.5 `AGENTS.md` 应是路由器和护栏，不是第二份 Changelog

OpenAI 官方文档说明，Codex 会从全局、仓库根目录到当前工作目录逐级发现并组合项目指令，更接近当前目录的规则优先；默认组合上限为 32 KiB。每个目录最多选择一个指令文件，优先级为 `AGENTS.override.md`、`AGENTS.md`、再到配置的 fallback filename。指令链通常在新运行/会话开始时建立，修改后应启动新运行确认实际加载结果。[Custom instructions with AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)

根 `AGENTS.md` 推荐只保留：

1. 项目一句话目标和范围边界；
2. 指令和事实来源优先级；
3. 文档阅读路由；
4. 不可违反的架构和安全边界；
5. 权威安装、测试、构建命令；
6. 改动类型到文档/测试的联动表；
7. Definition of Done；
8. commit、push、迁移、发布授权边界；
9. 长驻资源归属、清理和复核规则。

不建议放入逐日历史、长篇模块完成情况、每次测试数量、临时 SHA/Run、某一环境的详细状态或整份业务/API 说明。

本次审计机器实测（2026-09-08，使用 `wc -c`；当时未发现 `project_doc_max_bytes` 显式覆盖；用户级文件大小不是仓库可复现事实）：

| 文件 | 大小 |
|---|---:|
| 项目根 `AGENTS.md` | 30,777 bytes |
| 用户级 `~/.codex/AGENTS.md` | 10,044 bytes |
| 合计 | 40,821 bytes |
| `docs/06_ai/AI_CONTEXT.md` | 71,544 bytes |

这意味着当前项目存在上下文预算和重复事实风险。即使当前客户端成功载入了完整指令，也应把根文件精简为稳定规则和导航，将易变状态移入机器可读台账；模块特有规则放入就近的嵌套 `AGENTS.md`。对新项目，可把根文件约 8–12 KiB 作为工程目标，为全局规则、嵌套规则和任务上下文保留余量；这只是建议值，不是 OpenAI 的硬限制。

### 6.6 为文档和状态加元数据

权威文档可以使用统一头部：

```yaml
document_status: draft | accepted | superseded
authority: requirement | contract | architecture | implementation-note | evidence
owner: team-or-person
last_reviewed: YYYY-MM-DD
applies_to: module-or-version
supersedes: optional-document-id
```

状态含义必须固定：

- `draft`：可讨论，不能作为已冻结实现依据；
- `accepted`：需求或设计已经批准；
- `superseded`：由另一份明确记录替代。

文档生命周期与能力成熟度是两个维度。`implemented`、`verified`、`deployed` 和 `enabled` 只进入下面的能力台账，并分别绑定 SHA、环境和证据。不要再用一个不带环境和证据的“已完成”覆盖所有状态。

### 6.7 机器可读状态台账

```yaml
schema_version: 1

project:
  candidate_sha: "<git-sha>"
  milestone: "<milestone>"
  updated_at: "YYYY-MM-DDTHH:MM:SSZ"

capabilities:
  - id: AUTH-001
    contract:
      status: accepted
      document: "docs/requirements/auth.md"
    implementation:
      status: implemented
      sha: "<git-sha>"
    local_verification:
      status: passed
      sha: "<git-sha>"
      command: "<command>"
      environment: "<os/runtime/db>"
      verified_at: "<time>"
      evidence_ref: "<report-or-junit>"
    ci_verification:
      status: passed
      sha: "<git-sha>"
      run_id: "<run-id>"
      evidence_ref: "<artifact>"
    rehearsal:
      status: not_run
      sha: null
      environment: null
      evidence_ref: null
    deployment:
      status: not_deployed
      sha: null
      environment: null
      artifact_digest: null
    feature_flag: disabled

blockers:
  - id: BLK-001
    gate: production
    description: "<missing condition>"
    owner: "<owner>"
    due_at: null

release_decision:
  status: no-go
  exact_target: "<environment>"
  artifact_digest: null
  decided_by: "<human-or-null>"
  decided_at: null

provenance:
  machine_fields_refreshed_at: "<time>"
  human_fields_reviewed_at: "<time>"
```

脚本可以从 Git、锁文件、OpenAPI、迁移、CI 和 Release Manifest 生成或更新可确定字段；人工维护产品决策、授权和风险接受。两类字段应分开并记录来源与刷新时间。自动化不应默认 commit 状态文件，也不得覆盖人工 Go/No-Go 结论。

---

## 7. Skills、脚本、CI、Plugin 和 Connector 怎么分工

### 7.1 先分清载体

| 载体 | 适合承载 | 不适合承载 |
|---|---|---|
| `AGENTS.md` | 每次任务都适用的稳定规则和边界 | 易变状态、长教程、一次性流程 |
| 普通文档/ADR | 业务事实、理由、替代方案和后果 | 必须机械执行的检查 |
| Skill | 有触发条件、会重复、需要判断与编排的工作流 | 只有一条固定命令或一次性任务 |
| Script | 确定性、易出错、可重复的机械步骤 | 产品判断和开放式 Review |
| CI | 所有候选必须强制满足的门禁 | 只在特殊任务中才需要的长流程 |
| Plugin | 安装和分发一组 Skills、可选 App/Connector、MCP 配置、Hook 或展示资产 | 充当外部服务授权 |
| App/Connector | 面向用户/工作空间的已认证服务集成和动作 | 绕过源服务角色、数据范围或审批 |
| MCP Server | 通过协议暴露工具、资源或上下文，本地/远程均可 | 自动获得超出服务身份和运行时策略的权限 |
| Subagent | 并行探索、测试、审计、日志分析和独立 Review | 多人同时修改同一状态/文件 |

示例：

- “日志不得包含 Token”属于 `AGENTS.md` + Secret Scan；
- “怎样审查迁移”适合 Skill；
- “导出 OpenAPI”适合 Script；
- “生成物必须无漂移”适合 CI；
- “读取 PR 和 Run”适合 GitHub Connector；
- “为什么选 PostgreSQL”属于 ADR。

本手册据此采用以下工程分工：用 `AGENTS.md` 保存稳定规则，用 Skill 承载条件式重复流程，用 MCP/Connector 接入外部系统，用 Subagent 隔离可并行工作。OpenAI 官方将这些能力定义为互补的定制层。[Codex customization overview](https://learn.chatgpt.com/docs/customization/overview)

> **Plugin 是分发单元，不是授权单元。** 安装、可见、连接账户、源服务权限、单次读写批准和当前运行时策略是不同层级，不能相互替代。

### 7.2 Day 0 不要安装一大包 Skills

Skill 不能补救缺失的产品规则。需求未冻结时，自动化得越快，返工通常也越快。

推荐顺序：

1. 先准备精简 `AGENTS.md`、权威文档、命令和 CI；
2. 一个流程稳定、重复两三次后，再判断是否值得做 Skill；
3. 一个 Skill 只负责一个清晰任务；
4. 高风险写入 Skill 只允许显式触发；
5. Skill 调用已有确定性脚本，不复制脚本逻辑；
6. 暂时不用的 Skill 不安装、不启用；
7. 团队共用且含多个能力时再封装 Plugin。

Skills 使用渐进式加载。Codex 初始只暴露名称、描述和路径；初始 Skill 列表最多占模型上下文的 2%，上下文窗口未知时最多 8,000 字符。Skill 过多时描述可能先被缩短，部分 Skill 还可能不出现在初始列表。显式调用或描述匹配可以触发 Skill；选中后会读取完整 `SKILL.md`，配套引用、资产和脚本再按 Skill 指令及任务需要使用。因此描述必须短、具体，并同时说明触发和排除条件。[Build skills](https://learn.chatgpt.com/docs/build-skills)

### 7.3 新项目优先准备的项目级 Skills

截至本次审计，pinkdooHub 尚无仓库级 `.agents/skills/**/SKILL.md`；下表是建议从已经稳定的文档和脚本流程中逐步抽取的候选，不是当前已存在的能力。不建议第一天全部创建，应按流程成熟度逐步沉淀：

| Skill 候选 | 触发场景 | 必需输入 | 输出/停止条件 |
|---|---|---|---|
| `context-audit` | 长任务开始、阶段切换、文档冲突 | 根规则、状态台账、权威文档 | 事实、冲突、过期项；不改业务决策 |
| `feature-slice-delivery` | 实现已冻结的纵向功能 | 需求/API/数据/验收/允许范围 | 代码、测试、文档、证据、清理 |
| `contract-sync` | API/事件/生成类型变化 | 权威 Schema 和生成命令 | 兼容性分类、生成物、漂移结果 |
| `quality-gate` | 准备 Review/PR | 风险等级和改动范围 | 对应测试矩阵与 Review Report |
| `database-migration-review` | 表/字段/索引/约束/回填变化 | 设计、Model、迁移、历史起点 | 风险、SQL Review、演练计划；只读 |
| `database-migration-apply` | 已明确授权目标环境迁移 | 目标身份、备份、计划、确认字段 | 精确执行和证据；默认不隐式触发 |
| `release-readiness` | 构建 RC 或 Go/No-Go | SHA、Run、Artifact、环境、风险表 | 缺口与结论；不自动发布 |
| `security-review` | Auth、支付、上传、Webhook 或发布前 | 威胁模型、数据分类、代码/配置 | 风险等级、证据、修复门禁 |
| `incident-triage` | 告警、线上异常、数据不一致 | 只读遥测、Runbook、时间线 | 假设、证据、缓解选项；不擅自破坏性修复 |

建议把迁移 Review 与 Apply、Release Review 与实际发布分成不同 Skill，避免“检查一下”隐式升级为外部写入。

### 7.4 本次环境中可参考的通用 Skill 类别

下表使用便于阅读的能力简称，不保证是其他会话中的精确调用标识。Skill 是否存在、命名空间和触发规则取决于当前客户端、工作区、已安装 Plugin 和版本；实际使用前必须检查当次 `Available Skills`。例如本次环境中的完整名称包含 `deep-research-work:deep-research`、`sites:sites-building`、`documents:documents` 和 `product-design:index`。

| Skill | 在新全栈项目中的用途 | 何时不需要 |
|---|---|---|
| `openai-docs` | OpenAI API、Codex、自定义、模型、SDK 和产品能力的最新官方事实 | 项目完全不涉及 OpenAI/Codex 事实 |
| `skill-creator` | 把成熟重复流程做成项目 Skill | 一次性任务、流程尚未稳定 |
| `skill-installer` | 按明确来源安装真正需要的 Skill | 为“以后可能有用”批量安装 |
| `plugin-creator` | 将多个 Skill/工具/Connector 作为团队包分发 | 单仓库的一条简单流程 |
| `plugin-management:plugin-management` | 发现 Plugin、核对权限/依赖、管理连接或卸载 | 与外部系统无关，或只需普通本地工具 |
| `frontend-skill` | 创建视觉质量较高的站点、应用和原型 | 纯后端或已有完整设计系统 |
| `impeccable` | UI/UX、响应式、可访问性、性能和细节审查 | 后端-only 任务 |
| `webapp-testing` | 用真实浏览器验证本地 Web 功能、Console 和截图 | 只有纯函数/后端单元测试 |
| `figma-use` + 对应 `figma-*` | Figma 是设计权威源，需要读写、生成页面或设计转代码 | 没有 Figma 工作流；调用写工具前必须加载其前置 Skill |
| `product-design:*` | 明确的产品设计探索、审计、视觉复刻或原型 | 普通代码实现且用户未要求 Product Design |
| `imagegen` | 生成或编辑位图、插画、纹理、Mockup | SVG/图标系统或代码原生视觉更合适 |
| `documents`/`pdf`/`presentations`/`spreadsheets` | 交付物确实包含相应办公文件 | 普通 Markdown/代码任务 |
| `sites-building`/`sites-hosting` | 用 Sites 构建和托管网站 | 项目采用自己的仓库和部署链 |
| `deep-research` | 用户明确要求 Deep Research 时做深入研究 | 普通选型检索和日常技术调查 |

### 7.5 按需选择 Plugin/Connector

不要把所有外部系统都接入。按任务启用、最小权限、读写分离：

| 需要 | 可考虑 | 权限建议 |
|---|---|---|
| PR、Issue、CI、Release | GitHub Plugin/Connector | 日常审计先只读；合并/发布单独授权 |
| 安全专项 | Codex Security | 先扫描和报告；修复、豁免分开 |
| DNS/CDN/WAF/部署 | Cloudflare 或目标云 Connector | Preview/Plan 与 Apply 分开，限制环境 |
| 设计协作 | Figma/Canva | 只在设计确为权威源时连接 |
| 产品/项目管理 | Asana、Trello、ClickUp、Atlassian Rovo | 防止自动批量改状态或通知成员 |
| 文件/规格资料 | Google Drive、Dropbox、Box | 只访问指定目录，避免全盘读取 |

Plugin/Connector 的完整权限链应逐层确认：

| 层级 | 必须回答 |
|---|---|
| 可用性 | 这个 Plugin 是否安装并对当前用户/工作区可见？ |
| 能力 | 它包含哪些 Skills、App/Connector、MCP 或 Hook？ |
| 连接 | 当前用户是否已连接正确的外部账户？ |
| 源权限 | 该账户在 GitHub、云、文档或工单系统中实际能访问什么？ |
| 动作授权 | 本任务只允许读，还是明确允许某些写操作？ |
| 运行时 | 沙箱、审批策略和当前环境是否允许这个动作？ |
| 恢复 | 外部副作用如何撤销、补偿和审计？ |

默认先启用只读动作；写入单独批准，并记录业务 Owner、认证主体、允许数据范围、外部副作用和恢复方法。测试使用源服务内同样最小权限的测试账户。Skill、Prompt、Subagent 或安装状态都不能扩大原任务授权。

Plugin 可用性和安装状态应在任务开始时重新检查。Agent 不应因某个 Plugin 出现在推荐目录中就自动安装；应先确认真实能力缺口、数据范围、权限、Owner 和用户/管理员的明确授权。[技能与插件](https://learn.chatgpt.com/zh-Hans/docs/skills-and-plugins) · [插件和连接器控制](https://learn.chatgpt.com/zh-Hans/docs/enterprise/apps-and-connectors)

### 7.6 一个合格 Skill 的设计清单

每个 Skill 至少写清：

```text
1. 何时触发
2. 何时不得触发
3. 必需输入
4. 权威事实来源
5. 前置条件
6. 允许的副作用
7. 明确步骤
8. 验证方法
9. 停止条件
10. 输出格式
11. 资源清理要求
```

高风险 Skill 额外要求：

- 显式调用，不靠模糊自然语言触发；
- 在支持的配置中设置 `agents/openai.yaml` 的 `policy.allow_implicit_invocation: false`；
- 先解析并显示精确目标；
- 默认 dry-run/plan；
- Apply 需要冻结输入哈希、边界或版本；
- 拒绝未知基线和模糊环境；
- 不把 Skill 本身当成权限来源；
- 对“应触发、不应触发、边界情况”写测试 Prompt；
- 版本、Owner 和变更记录可追踪。

### 7.7 多代理怎样用才真正提效

适合并行：

- 产品/领域、架构/安全、栈/基础设施、质量/发布四路只读研究；
- 大型代码库不同目录探索；
- 安全、性能、可维护性独立 Review；
- 测试失败和日志分类；
- 多份文档的证据提取；
- 互不共享状态的测试任务。

不适合直接并行写：

- 同一文件或同一业务状态机；
- Lockfile、迁移、OpenAPI 和生成物；
- 后一步严格依赖前一步结果的连续决策；
- 生产数据库、云资源和第三方系统写操作。

确需并行写入时，必须分配无重叠的文件所有权；迁移、Lockfile 和生成物由一个集成者统一处理。主 Agent 负责冲突消解、最终完整验证和资源回收。OpenAI 官方也建议用 Subagent 隔离探索、测试和日志等高上下文工作，并注意并行 Agent 带来的成本和写冲突。[Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)

委派不扩大权限：只读父任务不能由 Subagent 变成写任务，外部 Connector 或生产操作也不能因转交而绕过授权。子代理结论只是待核对的候选证据；主 Agent 必须等待所需结果、解决相互冲突的结论并复核关键事实。小任务不为形式并行；无法使用隔离 Worktree 时，应明确所有 Agent 共享工作目录并继续保持文件所有权不重叠。

---

## 8. pinkdooHub 中哪些资产可以复用

### 8.1 复用分级矩阵

| 级别 | 内容 | 处理方式 |
|---|---|---|
| A：可直接抽成组织规范 | 事实源分层、授权边界、DoD、Review 维度、资源回收 | 去掉领域名后形成模板 |
| B：可参数化复用 | CI、OpenAPI drift、依赖审计、迁移/备份/恢复/Seed 脚本模式 | 抽配置和适配器，保留安全默认值 |
| C：只复用思想 | 分层方式、ORM、数据库、前端框架、Redis、单机 Compose | 为新项目重新 ADR 和 Spike |
| D：禁止直接复制 | 业务规则、错误码、Phase、Secret、真实数据、当前状态和历史证据 | 从新项目重新定义 |

### 8.2 高价值直接复用项

- 需求、API、数据库、架构、开发、AI、流程、前端和发布文档的分工；
- 业务期望与当前实现分别判断；
- 修改类型到文档联动表；
- 单向依赖和事务所有权原则；
- 输入/输出 Schema 与显式字段白名单；
- 正常、失败、权限、边界、事务回滚测试矩阵；
- Mock 外部边界，不 Mock 被测对象；
- OpenAPI → 前端类型 → CI 漂移检查；
- 生产数据库方言和真实并发 Gate；
- 迁移独立于应用启动；
- preview → 显式 apply → 备份 → post-check；
- 备份必须独立恢复；
- Artifact 绑定 SHA、Run、checksum/digest 和环境；
- 未实现外部能力默认关闭；
- Secret/PII/日志脱敏；
- No-Go 和 Deferred 可以是正确结果；
- 长驻资源记录所有权、精确停止并复核。

### 8.3 可抽取的现有文件和脚本模式

| 资产 | 当前路径 | 建议 |
|---|---|---|
| AI 协作规则 | `AGENTS.md` | 只抽稳定规则，剥离当前状态 |
| AI 文档路由 | `docs/06_ai/AI_CONTEXT.md` | 精简为导航/阅读路由 |
| 架构模板 | `docs/04_architecture/architecture.md` | 参数化技术栈，保留边界模板 |
| 编码规范 | `docs/05_development/coding_standards.md` | 抽通用版，再叠加语言规则 |
| Review 清单 | `docs/07_process/code_review_checklist.md` | 拆通用与 Auth/Payment/Upload 等专项 |
| 迁移流程 | `docs/07_process/database_migration_workflow.md` | 高度可复用 |
| ADR 结构 | `docs/08_frontend/adr/` | 高度可复用 |
| 风险 Spike 方法 | `docs/08_frontend/frontend_architecture.md` | 复用方法，不复制 Taro 结论 |
| 测试导航 | `tests/README.md` | 复用“领域 × 层级 × 环境”组织法 |
| CI | `.github/workflows/ci.yml` | 做成可配置 Starter |
| OpenAPI 导出 | `scripts/export_openapi.py` | 参数化路径和框架启动方式 |
| 依赖/仓库审计 | `scripts/ci/`、`security/dependency_audit/` | 抽阈值、allowlist 和报告格式 |
| 发布证据 | `docs/09_release/` | 抽 Gate、Risk、Runbook、Manifest 模板 |
| 可销毁环境 | `deploy/rehearsal/` | 参数化服务和生产方言 |
| 单机环境 | `deploy/gatea/` | 仅作为一种 Deployment Adapter |
| 安全批处理 | `app/tasks/`、`scripts/local/`、`scripts/release/` | 抽 preview/apply/backup/verify 框架 |
| 后端基础模块 | `app/common/`、`app/core/`、`app/middleware/`、`app/storage/` | 去业务耦合后形成 Starter |

### 8.4 可复用的安全批处理骨架

```text
preview()
  → 只读检查目标身份和基线
  → 输出输入哈希、范围上界、预计行数和异常统计

apply(expected_hash, expected_boundary)
  → 重查所有前置条件
  → 创建并验证备份
  → 稳定顺序、分批、锁后复验
  → 原子写入或明确补偿
  → post-check / reconcile
  → 生成不可覆盖 Evidence Manifest

retry()
  → 只处理明确可重试错误
  → 使用全新事务或明确幂等身份

failure()
  → fail-closed
  → 保留证据
  → 不静默跳过、不修改版本记录伪装成功
```

### 8.5 不能直接复制的内容

- Product/Order/Inventory/Wallet/Reservation 具体规则；
- MARD 221 色、每 10g 价格、店休和上海时区约束；
- 当前错误码号段和状态 Enum；
- Product ID 锁序等特定数据模型细节；
- FastAPI/Tortoise/Aerich/Taro 的结论和精确版本；
- M0–M7、Phase 4.x/9.x 和 Gate A/B 命名；
- 当前 CI 数量、历史 SHA、Run ID、主机路径和环境 No-Go 原因；
- 本地数据库、备份、合成凭据或任何真实 Secret。

---

## 9. 如何同时保证效率、质量和稳健性

### 9.1 使用“双循环”而不是每一步都跑所有检查

```text
快速内循环
  Format → Lint/Type → 最近单测 → 相关集成/组件 → 局部浏览器验证

可信交付循环
  完整测试 → 契约漂移 → 生产方言 → 构建 → 安全/依赖
  → 发布候选环境 → 备份/恢复/迁移 → E2E/真机 → Go/No-Go
```

效率来自让测试与风险匹配，不是删除最终门禁。

### 9.2 风险分级

| 风险 | 示例 | 开发内循环 | PR/RC |
|---|---|---|---|
| R0 | 文案、注释、纯文档链接 | 文档检查、Lint | 链接/格式检查 |
| R1 | 纯 UI、无状态展示、纯函数 | Unit/Component、类型、浏览器 | 完整前端质量门禁 |
| R2 | API、权限、普通数据写入、兼容变更 | 定向集成、契约、相关 E2E | 完整 Suite + 生产构建 |
| R3 | 认证、资金、库存、迁移、并发、基础设施、Provider | 相关全链、故障/回滚 | 生产方言、并发、恢复、安全、RC、人工 Gate |

### 9.3 每个功能都以纵向切片交付

一个切片应尽量同时包含：

- 用户可观察结果；
- 业务规则和非目标；
- API/事件契约；
- 数据和迁移影响；
- 后端用例；
- 前端状态与错误；
- 权限和隐私；
- 正常/失败/边界/并发测试；
- 监控与运维影响；
- 文档和证据。

如果切片太大，按用户可独立验收的状态拆分；不要按“先写所有 Repository”“再写所有页面”拆分。

### 9.4 风险先行，但不提前过度设计

优先做会推翻架构的 Spike：

- 真实数据库非空迁移；
- 目标平台生产构建和真机；
- 认证/支付 Provider 的 Sandbox 与回调；
- 大文件、媒体处理或 AI 成本/延迟；
- 实时协作冲突模型；
- 云平台网络、Secret 和后台任务限制。

不为“以后也许会有”提前引入微服务、Broker、搜索集群、多区域或 Kubernetes。把未来演化接口留清楚即可。

### 9.5 把机械检查变成自动门禁

可逐步自动化：

- 分层 import 方向；
- API 不直接访问 Model/Repository；
- Schema 不依赖 ORM Model；
- 业务异常不用裸 HTTPException；
- 响应不直接返回 ORM 对象；
- 敏感字段不进入 Out Schema/日志；
- 新路由有认证、权限和错误测试；
- OpenAPI/生成类型无漂移；
- Model、迁移、数据库文档/DBML 一致；
- 新错误码同步索引；
- 迁移文件没有被重写；
- 文档链接和状态元数据有效；
- `AGENTS.md` 合并字节预算；
- Skill 引用存在、触发/不触发用例通过；
- 仓库无 Secret、临时产物和意外大文件。

### 9.6 测试矩阵

| 层级 | 目的 | 典型内容 |
|---|---|---|
| Unit | 快速证明纯规则 | Validator、金额/时间、状态机、Runtime Guard |
| Component | 证明 UI 局部行为 | 状态、错误、可访问性、交互 |
| Repository/Integration | 证明查询和事务 | 约束、锁、回滚、分页、N+1 |
| API Contract | 证明输入/输出/错误 | OpenAPI、严格 Schema、权限矩阵 |
| Full-stack E2E | 证明真实网络旅程 | 浏览器/客户端 → API → DB |
| Production-dialect | 证明方言和并发 | 迁移、Enum/Decimal、死锁、EXPLAIN |
| Provider Contract | 证明外部边界 | Sandbox、签名、Webhook、结果未知 |
| Release Rehearsal | 证明可交付和可恢复 | Artifact、部署、备份、恢复、故障 |
| Device/Platform | 证明目标载体 | 真机、浏览器、包体、平台审核 |

### 9.7 小改动、小证据、小合并

- 一个逻辑单元对应一组契约、代码、测试和文档；
- 先做可 Review 的小差异，再扩展下一个切片；
- 不把无关重构、依赖升级和功能混在一起；
- 同一迁移/Lockfile/生成物由一个 Owner 处理；
- 每个关键失败保留日志和根因，不靠反复重跑抹平；
- 高风险功能先以 Feature Flag 默认关闭；
- 只有上一层证据通过，才进入下一层环境。

### 9.8 Definition of Done

```text
Contract
  目标行为、边界、兼容性和非目标已明确

Code
  实现满足架构、安全和可维护性约束

Test
  与风险匹配的正常、失败、权限、边界和恢复路径通过

Documentation
  权威需求、API、数据、架构和运行文档已同步

Evidence
  结果绑定 SHA、命令、环境、时间和 Artifact

Cleanup
  任务创建的进程、端口、容器、浏览器、临时目录和 Secret 已回收并复核
```

Commit 是承载逻辑单元的方式，但 commit 本身不能证明正确或已部署；是否 commit/push/release 仍由任务授权决定。

---

## 10. 数据、迁移、安全和发布的稳健底线

### 10.1 数据库迁移是独立产品

任何表、字段、约束、索引或数据语义变化，都应回答：

- 哪个数据库方言和最低版本是权威？
- 从哪些历史版本升级？
- 是否锁表、重写数据、增加临时空间或长事务？
- DDL 是否能整体回滚？如果不能，部分失败如何修复？
- 旧应用和新应用能否短时间同时运行？
- 是否需要 expand → backfill → switch → contract？
- 如何预览影响行数和异常数据？
- 如何备份、独立恢复和对账？
- 失败后回滚应用、前滚数据库还是保持停写？

共同准备阶段：

```text
只读基线审计
  → 冻结候选 SHA / 迁移计划
  → 新鲜备份
  → 独立恢复验证
  → 可销毁环境重放历史升级
```

之后按项目的停机约束选择一条路径，不能把 pinkdooHub 的停机式单机流程当成所有系统的固定答案。

```text
路径 A：允许停机的受控迁移
停写/限流
  → 迁移
  → Backfill
  → Reconcile
  → 部署候选制品
  → Smoke/E2E
  → 分阶段启用
  → 观察与关闭窗口

路径 B：需要兼容窗口的 Expand / Contract
向后兼容的 Expand Schema
  → 部署可兼容新旧 Schema 的代码
  → 双写或可控双读（按设计）
  → 在线分批 Backfill + Reconcile
  → 切换读写路径并观察
  → 停止旧版本
  → 单独候选执行 Contract
  → 再次验证与观察
```

Expand/Contract 也不自动等于零停机：锁表、索引构建、复制延迟、双写失败和长 Backfill 都需要在目标版本与代表性数据量下演练。

禁止用 `fake`、手工改版本表、运行时自动建表或“目标表已经存在”伪装迁移成功。

### 10.2 一致性用多层防线

高风险状态变更通常需要组合：

- 输入 Schema 和业务 Validator；
- 数据库 CHECK/UNIQUE/FK；
- 事务；
- 行锁或乐观并发版本；
- 稳定锁顺序；
- 锁后复验；
- 幂等身份和意图一致性检查；
- 不可变流水/审计；
- 对账任务；
- 并发与故障测试。

不要把“客户端按钮禁用”当授权或幂等保证，也不要在局部 SQL 失败后只重试最后一步而破坏整个用例的原子性。

### 10.3 安全基线

- 明确资产、角色、信任边界和威胁模型；
- 服务端做认证、授权和资源归属判断；
- Secret 不进代码、日志、Prompt、构建产物和客户端包；
- 外部输入在边界做类型、长度、格式、数量和内容校验；
- 日志脱敏但保留定位所需上下文；
- 上传校验内容，不只信 MIME/扩展名；
- Webhook 校验签名、时间窗、防重放和幂等；
- 依赖锁定、漏洞审计、许可证、SBOM 和最终镜像扫描；
- 权限最小化，开发/CI/预发布/生产 Secret 分离；
- 安全例外有 Owner、期限、范围和恢复方案。

OWASP ASVS 可作为 Web 应用安全验证要求和测试基线的候选，但需要按项目风险裁剪，而不是机械勾选。[OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/)

### 10.4 Release Evidence Manifest

每个候选应自动生成不可覆盖的证据清单：

```yaml
release_candidate:
  repository: "<owner/repository>"
  source_ref: "<branch-or-tag>"
  source_head_sha: "<pr-head-or-source-sha>"
  tested_sha: "<checkout-or-merge-ref-sha>"
  build_sha: "<artifact-source-sha>"
  source_tree_clean: true
  created_at: "<utc-time>"

artifacts:
  app_image:
    target: "backend/linux-amd64"
    source_sha: "<build-sha>"
    build_runtime: "<builder-and-version>"
    public_config_fingerprint: "<non-secret-sha256>"
    digest: "<registry/name@sha256:digest>"
  frontend:
    target: "<web-weapp-ios-android>"
    source_sha: "<build-sha>"
    build_runtime: "<builder-and-version>"
    public_config_fingerprint: "<origin-app-id-and-public-flags-sha256>"
    checksum: "<sha256>"
  openapi_checksum: "<sha256>"

verification:
  ci_run: "<run-id-or-url>"
  run_attempt: "<attempt>"
  checkout_sha: "<tested-sha>"
  required_jobs: ["..."]
  test_reports: ["..."]
  dependency_audit: "<artifact>"
  migration_rehearsal: "<report>"
  backup_restore: "<report>"

environment:
  name: "<staging-or-production>"
  database_product: "<name-version>"
  migration_version: "<version>"
  deployed_artifact: "<digest>"
  runtime_config_fingerprint: "<non-secret-sha256>"
  deployment_record_id: "<id>"

decision:
  status: "go | no-go | conditional"
  approver: "<human>"
  blockers: ["..."]
  rollback_trigger: "<measurable condition>"
```

Manifest 必须验证而不只是记录这些身份：

- `artifact.source_sha == build_sha`；
- 默认 `build_sha == tested_sha`，禁止部署只构建、未测试的源；
- 若 CI 测试 PR merge-ref，必须保存 source head 与 merge-ref 的关系，并在最终合并提交重新验证，或执行已批准且有证据的等价策略；
- `deployed_artifact == rehearsed_artifact == approved_artifact`；
- 不同环境编译的客户端分别保存 target、构建运行时、公开配置指纹、checksum 和 Manifest；
- 任何 Secret 都不进入公开配置指纹，只记录 Secret 版本/引用 ID 或部署记录。

CI Artifact 用于在 Job 之间保存构建产物、测试结果和证据；应配合 checksum、保留期和 SHA 绑定，不能把不同提交的绿色结果拼成一个候选。[GitHub Actions artifacts](https://docs.github.com/en/actions/concepts/workflows-and-actions/workflow-artifacts)

---

## 11. pinkdooHub 当前最值得提升的地方

以下是从本次审计得到的改进路线，不是对本任务的实现承诺。

### P0：上下文瘦身和单一状态源

现状：根 `AGENTS.md` 与用户级规则合计超过 Codex 官方默认组合预算，`AI_CONTEXT.md` 也已很大；Phase、测试数、SHA、环境状态在多个位置重复，并已有轻微漂移。

建议：

1. 新增 `current-state.yml` 或 `release-status.yml`；
2. 由脚本生成面向人的 `CURRENT_STATUS.md`；
3. 根 `AGENTS.md` 只保留稳定规则、导航和授权边界；
4. 后端、前端、迁移、发布使用就近嵌套规则；
5. Changelog 按版本拆分，历史归档；
6. CI 检查指令字节预算、状态字段和文档链接；
7. 其他文档链接状态源，不再复制整段当前状态。

### P0：把 Gate A 新候选闭环固化为单一状态源

截至 2026-09-08，真实 Gate A 已用新候选完成完整 CI、匹配镜像、新 Backup/Restore、M2→M7、钱包发布前准备、MARD 色板导入和候选韧性验证；第一次因 Runtime Secret 注入问题在 M3 DDL 前停止的记录仍应作为失败证据保留，但不能继续代表当前数据库状态。下一步不是重放旧 Evidence，而是把候选 SHA、CI Run、镜像、迁移、备份、恢复、代表性数据及仍受域名约束的外部门槛汇总到机器可读状态源，并由文档引用该状态源。

### P1：让生产数据库方言更早进入日常开发

- 提供一键、专用 Schema 的 MySQL 8+/Redis 本地或 CI 环境；
- SQLite 继续服务快速单元/集成反馈；
- 类型、迁移、锁、死锁、并发和查询计划在每个高风险模块阶段验证；
- 新项目优先考虑开发/CI/生产使用同类数据库。

### P1：补齐后端静态质量门禁

当前可考虑分阶段引入 Ruff 和 mypy/pyright：

- 新代码和基础模块先严格；
- 旧代码建立明确 baseline，不要求一次清零；
- 增加 import 依赖方向检查；
- 与现有 pytest/MySQL 门禁并行，而不是替代行为测试。

### P1：拆分依赖并提升供应链证据

- runtime、development、test、migration/audit 依赖分组；
- 生产镜像只安装 runtime；
- 使用可复现 lock/hash；
- 基础镜像固定 digest；
- GitHub Actions 固定到受信 commit；
- 生成 SBOM、扫描最终镜像、记录许可证；
- 建立运行时和依赖 EOL/升级窗口。

### P1：从“有日志”提升到 SLO 和告警闭环

- 统一 JSON 日志和 request/trace ID；
- HTTP RED、主机/容器 USE；
- DB 连接、慢查询、锁等待；
- Redis、Worker/Outbox、Provider 指标；
- 资金/库存/订单等业务不变量告警；
- 告警送达、静默、升级和恢复演练；
- 为核心旅程定义 SLI/SLO 和可量化回滚阈值。

### P1：完整抽象对象存储与异步任务边界

上传主链已经有存储 Protocol 和补偿思想；切换对象存储前，还应让清理、批量删除和重试同样依赖抽象能力。Reservation N2 进入实现时继续使用事务 Outbox + 独立 Worker，避免用 Web 进程内后台任务冒充可靠通知。

### P2：建立可移植 Starter，而不是复制整个业务仓库

Starter 可以包含：

- 精简 `AGENTS.md` 和任务模板；
- 文档目录与 ADR 模板；
- 配置、统一错误、日志、request ID、健康检查；
- API 契约导出/生成/漂移；
- 测试工厂和合成 Seed；
- 基础 CI、安全与仓库卫生；
- 可销毁真实数据库；
- Deployment Adapter 接口；
- Release Manifest 和资源清理框架。

业务 Model、状态机、错误码和当前项目 Phase 不进入 Starter。

### P2：IaC 和制品晋级

- 使用 IaC 表达网络、身份、Secret 引用和托管资源；
- 服务端由 CI 构建一次并按同一 Digest 逐环境晋级；带环境编译配置的客户端按同一干净 SHA 分环境生成并绑定各自 Manifest；
- 受保护环境保留人工审批；
- 自动生成而不是手抄 Release Evidence；
- 自动执行 Plan、备份/恢复演练和发布后观察，但不自动越权 Apply。

---

## 12. 一套可直接采用的新项目迭代计划

时间只作为小团队参考；Gate 通过比周数更重要。

| 迭代 | 目标 | 主要工作 | 必须看到的结果 |
|---|---|---|---|
| 第 0 周 | 产品和约束冻结 | Brief、旅程、词汇、NFR、风险、外部前置 | 范围/非目标清楚，关键人确认 |
| 第 1 周 | 选型和 Spike | 前后端/DB/部署候选、ADR、最高风险实验 | 真实实验关闭架构未知项 |
| 第 2 周 | 工程底座 | Repo、CI、配置、日志、健康、首迁移、部署 Preview | 干净 checkout 可复现 |
| 第 3 周 | 第一条纵向链路 | UI→API→DB→部署→E2E | 一个高价值流程可真实演示 |
| 第 4～5 周 | 风险优先切片 | 权限、主业务、外部端口、管理能力 | 每个切片独立满足 DoD |
| 第 6 周 | 硬化 | 并发、幂等、性能、安全、生产方言、非空迁移 | R2/R3 对应验证门禁通过 |
| 第 7 周 | 发布演练 | 不可变制品、备份/恢复、故障、回滚、清理 | 可销毁环境完整证据 |
| 第 8 周 | 持久验收/Go-No-Go | 真实起点迁移、E2E/设备、告警、容量、审批 | 明确 Go/No-Go，不带模糊债务上线 |

对简单内容站可合并 G2～G5；对资金、医疗、隐私、工业或强合规系统，应增加独立安全、数据和人工审计，不要为了套八周计划压缩门禁。

### 12.1 Day 0 清单

- [ ] 一句话说明用户问题和产品价值
- [ ] 列出三个核心旅程和明确非目标
- [ ] 冻结领域词汇和角色/权限草图
- [ ] 标出钱、权限、隐私、不可逆数据和外部 Provider
- [ ] 写下流量、延迟、RPO/RTO、地区、合规和预算假设
- [ ] 给每个外部前置条件指定 Owner 和最迟日期
- [ ] 指定需求、API、数据、架构、状态和证据权威源
- [ ] 创建最小 `AGENTS.md` 和任务 Brief
- [ ] 决定最高风险的两个 Spike
- [ ] 明确未授权操作：生产写入、迁移、发布、外部发送

### 12.2 首个纵向切片清单

- [ ] 有用户可观察的完成结果
- [ ] 需求和非目标已接受
- [ ] API/事件和错误契约已冻结
- [ ] 数据约束、索引和迁移已设计
- [ ] 服务端认证、权限和输出白名单到位
- [ ] 前端 loading/success/empty/error/unknown 状态到位
- [ ] 正常、失败、权限和边界测试到位
- [ ] 真实网络 E2E 能运行
- [ ] 日志/指标可定位该旅程
- [ ] 从干净环境可构建部署
- [ ] 文档、证据和资源清理完成

---

## 13. 可直接复制的任务模板

### 13.1 实现任务 Brief

```markdown
# 任务
[一句话描述最终结果]

## 用户可观察结果
[用户完成什么操作后看到什么]

## 权威输入
- 业务规则：[路径]
- API/事件契约：[路径]
- 数据设计：[路径]
- 架构约束：[路径]
- 当前状态/SHA：[路径或值]
- 相关测试：[路径]

## 范围
### 包含
- [...]

### 不包含
- [...]

## 验收标准
- Given [...], when [...], then [...]
- 正常路径：...
- 失败路径：...
- 权限路径：...
- 边界值：...
- 并发/重试/幂等：...

## 兼容性与风险
- 支持版本：...
- 数据是否保留：...
- 安全与隐私：...
- 数据库/Provider/持久环境影响：...

## 已知假设与待决策事项
- 已接受假设：...
- 会改变实现但尚未解决的决策：...
- 文档冲突处理：先报告，不在受影响范围内自行选择

## 外部来源
- 官方页面：...
- 查询日期：...
- 适用版本：...

## 允许的操作
- 可修改：[目录]
- 可运行：[命令]
- 可创建的临时资源：...

## 默认未授权操作
- 不 commit 或 push，除非本任务明确授权
- 可以在任务范围内生成和 Review 迁移文件
- 不把迁移应用到任何持久、共享、预发布或生产数据库
- 不 deploy、发布、提审或向外部分发
- 不修改共享或生产环境
- 不新增生产依赖，除非本任务明确授权并完成依赖评估
- 不向外部系统发送消息或执行写操作

## 验证
- 开发内循环：...
- PR Gate：...
- RC Gate：...

## 交付
- 修改内容
- 测试及结果
- 文档影响
- 迁移/依赖/版本影响
- 未验证事项
- 资源清理结果
```

### 13.2 只读调查 Brief

```markdown
只读分析，不修改文件，也不执行外部写操作。

目标：
[需要回答的决策]

请先读取：
[权威文件]

输出：
1. 当前事实；
2. 证据，使用文件/行号、命令或官方来源；
3. 文档、代码和测试之间的冲突；
4. 如果目标包含决策，给出两到三个真实可行方案及取舍；如果只是事实核验，直接给结论、证据、不确定性和待验证项；
5. 需要决策时给出推荐方案和理由；
6. 仍需人工决定的事项；
7. 未能验证的内容；
8. 资源清理结果。

不得把 Draft 当作已接受设计，不得把仓库实现表述为已部署能力。
```

### 13.3 Subagent 只读任务 Brief

```markdown
# Subagent Task

- 子任务目标：...
- 模式：只读
- 权威输入：...
- 与其他 Agent 不重叠的范围：...
- 禁止操作：不修改文件、不执行外部写入、不扩大父任务权限

## 必须返回
1. Findings
2. Evidence（文件与行号、命令或官方来源）
3. Conflicts
4. Recommendation
5. Unverified
6. Changes / Resources

不要返回大段原始日志；保存必要证据并返回摘要和引用。
```

### 13.4 ADR 模板

```markdown
# ADR-NNN: [决策标题]

- Status: Proposed | Accepted | Superseded
- Date: YYYY-MM-DD
- Owners: ...

## Context
[问题、约束、为什么现在必须决定]

## Decision drivers
- ...

## Options
### A. ...
### B. ...
### C. ...

## Decision
[选择和适用范围]

## Why
[证据与权衡]

## Consequences
- 正面：...
- 负面：...
- 迁移/退出成本：...

## Validation
[Spike、Benchmark、测试和生产门禁]

## Revisit triggers
[什么事实变化时重审]
```

### 13.5 Go/No-Go 最小模板

```markdown
# Release Decision

- Source head SHA:
- Tested/checkout SHA:
- Build SHA:
- Artifact digest/checksum:
- Target environment:
- Migration version:
- Required CI run:
- Decision: GO | NO-GO | CONDITIONAL

## Required evidence
- [ ] 同一 SHA 的必需 Job 全绿
- [ ] Source head、tested/checkout、build SHA 的关系可证明
- [ ] Artifact source SHA 与 build SHA 一致，部署/演练/批准的 digest 一致
- [ ] 真实起点只读审计
- [ ] 新鲜备份和独立恢复
- [ ] 迁移/Backfill/Reconcile 演练
- [ ] 安全、依赖和 Secret 检查
- [ ] E2E/真机/Provider 按适用范围验收；不适用项记录 N/A 和理由
- [ ] SLO、告警、值守和观察窗口
- [ ] 回滚/前滚触发条件
- [ ] P0 已关闭；P1 已关闭或有更高级批准的限时例外

## Blockers
- ID / Owner / Due / Evidence

## Approval
- Approver:
- Time:
- Scope:
- Authorized action:
- Exact target:
- Artifact digest:
- Authorization expires at:
- Rollback authority:
```

任一适用的 Required Evidence 缺失时必须 `NO-GO`。`CONDITIONAL` 只适用于所有阻断门槛已经满足、仅剩明确非阻断条件的情况；每个条件都要有 Owner、期限、影响范围、复核证据和未满足时的停止/回滚动作。它不得绕过安全、迁移、备份恢复、Secret、Artifact 身份或核心 E2E 门槛。一次批准只覆盖记录中的具体动作、环境和 Artifact，不自动延伸到提审、正式发布、另一个环境或另一个 SHA。

---

## 14. 常见反模式

- 先确定框架，再为框架寻找问题；
- 让 AI 在没有业务规则时自行补齐资金、权限和状态机语义；
- 把所有上下文塞进根 `AGENTS.md`；
- 用一份巨大的 `AI_CONTEXT.md` 同时保存规则、状态和历史；
- 同一事实复制到 README、AGENTS、Changelog 和 Release 文档；
- 安装所有 Skills 和 Connectors，期待 AI 自动变可靠；
- 把一个“万能全栈 Skill”用于设计、实现、迁移和发布；
- 多 Agent 同时修改同一文件、Lockfile 或迁移；
- 先横向写完所有后端，再第一次接前端；
- 在业务成熟前引入微服务、消息集群和 Kubernetes；
- 用 SQLite/Mock 通过证明生产数据库、支付或真机可用；
- 应用启动时自动执行生产迁移；
- 用 `latest`、不同 SHA 的测试或现场重新构建作为发布候选；
- 只创建备份但从未独立恢复；
- 对网络超时自动重发非幂等写请求；
- 用客户端按钮状态代替服务端权限和幂等；
- 为赶进度关闭 TLS、鉴权、证书校验或审计；
- 把 No-Go 当失败而隐藏阻断项；
- 任务结束不清理容器、端口、浏览器、临时 Secret 和测试数据。

---

## 15. 最终决策检查表

在让 AI 开始大型实现前，应能回答：

- [ ] AI 是否知道目标用户、核心旅程和明确非目标？
- [ ] 哪份文件决定业务行为？
- [ ] 哪份文件决定 API/事件？
- [ ] 哪份文件决定数据结构和迁移？
- [ ] 契约文档是 Draft、Accepted 还是 Superseded？
- [ ] 能力是 Implemented、Verified、Rehearsed、Deployed、Enabled 还是 UAT Accepted？
- [ ] 当前候选的 source head、tested/checkout、build SHA 与 Artifact 分别是什么，彼此关系是否可证明？
- [ ] 本地、CI、演练、预发布和生产有哪些关键差异？
- [ ] 选型是由哪些约束和 Spike 证据推导的？
- [ ] 当前为什么需要 Redis、Queue、Search、微服务或 Kubernetes？
- [ ] 服务器选择包含 RPS、延迟、内存、连接、IOPS、RPO/RTO 和运维成本吗？
- [ ] 出错后如何回滚、前滚、恢复和对账？
- [ ] 哪些测试属于内循环、PR Gate 和 RC Gate？
- [ ] 哪些 Skills 真正重复且有清晰触发条件？
- [ ] 哪些规则应该由 Script/CI 强制，而不是写进 Skill？
- [ ] 是否给 AI 暴露了真实 Secret 或未脱敏数据？
- [ ] 外部平台、备案、证书、账号、商户资质或真机是否有 Owner？
- [ ] 哪些操作已授权，哪些没有？
- [ ] 任务结束要回收哪些服务、容器、端口和临时资源？

如果这些问题没有答案，应先补上下文或做小型 Spike，而不是扩大实现范围。

---

## 16. 参考资料

### 16.1 pinkdooHub 仓库内依据

- [项目根 AGENTS](../../AGENTS.md)
- [GitHub Actions CI](../../.github/workflows/ci.yml)
- [Tests README](../../tests/README.md)
- [Gate A Operations](../../deploy/gatea/README.md)
- [CI Scripts](../../scripts/ci/)
- [Release Scripts](../../scripts/release/)
- [项目 AI Context](../06_ai/AI_CONTEXT.md)
- [Architecture](../04_architecture/architecture.md)
- [Coding Standards](../05_development/coding_standards.md)
- [Changelog](../05_development/changelog.md)
- [Code Review Checklist](code_review_checklist.md)
- [Database Migration Workflow](database_migration_workflow.md)
- [Frontend Architecture](../08_frontend/frontend_architecture.md)
- [Frontend ADR Index](../08_frontend/adr/README.md)
- [Frontend Testing Strategy](../08_frontend/testing_strategy.md)
- [Release Documents](../09_release/README.md)
- [CI Gate Matrix](../09_release/ci_gate_matrix.md)
- [Release Drill Runbook](../09_release/release_drill_runbook.md)
- [Go/No-Go Checklist](../09_release/go_no_go_checklist.md)
- [Environment and Secrets](../09_release/environment_and_secrets.md)

### 16.2 官方外部依据

以下链接用于解释 Codex、主流框架、基础设施和安全能力；技术版本、价格和平台限制在新项目正式选型时必须重新核对：

- [Codex customization overview](https://learn.chatgpt.com/docs/customization/overview)
- [Custom instructions with AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Build skills](https://learn.chatgpt.com/docs/build-skills)
- [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [技能与插件](https://learn.chatgpt.com/zh-Hans/docs/skills-and-plugins)
- [插件和连接器控制](https://learn.chatgpt.com/zh-Hans/docs/enterprise/apps-and-connectors)
- [FastAPI features](https://fastapi.tiangolo.com/features/)
- [FastAPI async guidance](https://fastapi.tiangolo.com/async/)
- [Django tutorial](https://docs.djangoproject.com/en/5.2/intro/tutorial01/)
- [NestJS introduction](https://docs.nestjs.com/introduction)
- [Spring Boot](https://docs.spring.io/spring-boot/)
- [Go database access](https://go.dev/doc/database/)
- [Next.js deployment](https://nextjs.org/docs/app/getting-started/deploying)
- [SQLite: Appropriate Uses](https://www.sqlite.org/whentouse.html)
- [OpenAPI Specification](https://spec.openapis.org/oas/latest.html)
- [Docker Compose in production](https://docs.docker.com/compose/how-tos/production/)
- [Kubernetes production environment](https://kubernetes.io/docs/setup/production-environment/)
- [Cloud Run autoscaling](https://docs.cloud.google.com/run/docs/about-instance-autoscaling)
- [Azure Container Apps overview](https://learn.microsoft.com/en-us/azure/container-apps/overview)
- [AWS Well-Architected: testing data recovery](https://docs.aws.amazon.com/wellarchitected/latest/reliability-pillar/back-up-data.html)
- [OpenTelemetry signals](https://opentelemetry.io/docs/concepts/signals/)
- [OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/)
- [GitHub Actions artifacts](https://docs.github.com/en/actions/concepts/workflows-and-actions/workflow-artifacts)

---

## 17. 本文的维护规则

- 本文主要维护跨项目方法和模板，只保留明确标注审计日期的高层项目快照；不持续复制频繁变化的 SHA、测试数量、环境勾选和逐项 Blocker，实时状态以机器台账、最新 changelog 和 Release Evidence 为准；
- 新项目采用本文建议时，必须用自己的 ADR 重新决定技术栈、数据库、部署和安全模型；
- 任何会随时间变化的版本、价格、平台和合规信息都应在决策当天查官方来源；
- 方法发生长期变化时更新本文；项目一次性历史进入 Changelog 或 Release Evidence；
- 若本文与模块权威需求、API、数据库设计或明确发布记录冲突，以更具体的权威文件为准，并修复本文中的通用表述。

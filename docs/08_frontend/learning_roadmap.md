# pinkdooHub 前端学习路线

> **Document Version:** v0.7
> **Status:** Draft
> **Last Updated:** 2026-08-29
> **Audience:** 首次系统学习 JavaScript、TypeScript、React 与 Taro 的项目开发者

本项目采用“知识点 → 小练习 → 真实功能 → 测试 → 复盘”的循环，不要求先学完全部前端理论再开始，也不把复制示例代码当作掌握。

---

## 1. 每个阶段的固定学习循环

1. 阅读本阶段概念和官方资料；
2. 写一个不超过单一职责的小练习；
3. 为练习补正常、失败和边界测试；
4. 把概念用于真实页面/Feature；
5. 在微信与 H5 观察运行行为；
6. 主动制造一次错误并读懂报错；
7. 运行本阶段质量门槛；
8. 在 `docs/08_frontend/learning_notes/` 写短复盘。

复盘回答：

- 今天新增了什么概念？
- 它解决了什么真实问题？
- 最容易混淆的点是什么？
- 哪个测试防止了哪种错误？
- 下次如何独立定位？

---

## 2. 阶段路线

| 阶段 | 工程交付 | 新知识 |
|------|----------|--------|
| 0 | 架构文档与 ADR（已完成 2026-08-15） | 架构、边界、ADR、API 契约 |
| 1 | TypeScript 纯函数练习 | JS 运行时、类型、模块、Promise |
| 2 | 四端 Taro Spike（已完成 2026-08-15） | Node/npm、Taro、编译、项目配置 |
| 3 | 正式脚手架（已完成 2026-08-20 依赖复核） | React 组件、TSX、Props、事件 |
| 4 | OpenAPI 类型 + HTTP Client 基础（已完成 2026-08-20） | 泛型、unknown、async、错误、JWT |
| 5 | 登录纵向链路（代码、自动化与微信开发者工具 Functional 已完成 2026-08-20） | State、Context、Effect、Storage |
| 6 | Product | 列表、分页、派生状态、组合算法 |
| 7 | Order | 表单、状态机、幂等、未知结果 |
| 8 | Admin | 权限、上传、复杂表单、审计 |
| 9 | 微信发布 | HTTPS、合法域名、安全、CI、迁移、E2E 与发布 |

---

## 3. 阶段 0：架构与契约

学习：

- 客户端、服务端、API；
- 分层和依赖方向；
- 什么是架构目标/非目标；
- ADR 为什么记录理由和代价；
- OpenAPI、HTTP Method、Header、Body、Query；
- HTTP status 与业务 code；
- Build、Smoke、Functional。

实践：

- 阅读本目录五份主文档与六个 ADR；
- 用自己的话画出 Page 到 FastAPI 的调用链；
- 从 OpenAPI 找到登录、商品、订单、库存端点；
- 找出一个文档计划和实际 OpenAPI 的差异。

完成标准：能解释为什么业务页面不能直接请求后端，以及为什么隐藏管理按钮不等于权限控制。

---

## 4. 阶段 1：JavaScript 与 TypeScript

先学：

- `const`/`let`；
- string/number/boolean/null/undefined；
- object/array；
- function/arrow function；
- map/filter/find/reduce 的基本用途；
- module import/export；
- Promise 与 async/await；
- interface/type；
- union、可选字段、泛型；
- unknown、类型收窄和 Guard；
- 不可变数据更新。

暂不学：装饰器、高级条件类型、类型体操、复杂类继承。

项目练习：

```text
formatMoney
formatUtcDate
isApiEnvelope
parsePositiveId
resolveAssetUrl
findMatchingExperienceOption
buildOrderItem
```

测试：正常、null/undefined、非法输入、边界和未知 Enum。

关键认识：TypeScript 不改变 JavaScript 运行时；有 TS 类型不代表网络 JSON 真实符合类型；`number` 不能自动解决金额精度。

---

## 5. 阶段 2：Node、npm 与 Taro Spike

学习：

- Node 与浏览器/小程序运行时的区别；
- npm、package、dependency、devDependency、lockfile；
- 本地 CLI 与全局 CLI；
- Taro source/build output；
- `weapp/alipay/tt/h5`；
- Webpack 5 编译；
- 平台开发者工具；
- 环境变量与 secret 的区别。

实践：

- 创建临时最小 Taro React TypeScript 应用；
- 四端生产构建；
- 微信/H5 打开页面；
- 验证一组候选 UI 组件；
- 验证 Request、Upload、Storage；
- 验证 Jest/Taro Test Utils。

完成标准：能解释同一 TSX 如何生成四种平台产物，并能区分编译错误、React 错误和平台运行错误。

---

## 6. 阶段 3：React 基础与正式脚手架

学习顺序：

1. JSX/TSX；
2. 函数组件；
3. Props；
4. 条件/列表渲染和稳定 key；
5. 事件；
6. `useState`；
7. 受控表单；
8. 组件组合。

练习：

- `ProductCard`；
- `PageState`；
- `OrderStatusCard`；
- 登录表单；
- 数量 Stepper。

注意：Props 只读；State 不直接修改；不要用数组 index 当会变化列表的 key；不要在 render 中执行请求。

---

## 7. 阶段 4：请求、错误和异步

> **基础层状态：已完成。** OpenAPI 导出/生成、Transport、信封 Guard、错误分类、取消、Bearer 与 single-flight refresh 已实现并有单元测试；auth Endpoint、真实 Session/Storage 和登录页面属于阶段 5。

学习：

- HTTP 与 Taro.request；
- 泛型 `ApiEnvelope<T>`；
- Runtime Guard；
- Promise 并发；
- Abort/Timeout；
- Bearer JWT；
- Refresh single-flight；
- 错误分类；
- 幂等与自动重试边界；
- Dependency Injection 的简单形式。

实践：

- fake transport；
- 登录成功；
- HTTP 400 + 1006；
- 三请求共享 refresh；
- 403 不刷新；
- empty-body PATCH；
- upload adapter。

完成标准：页面看不到 Token 和信封细节；能解释为什么创建订单超时后不能自动再 POST。

---

## 8. 阶段 5：React Effect、Context 与认证

> **账号密码主链状态：已完成。** login/register/refresh/logout/getMe Endpoint、Session Manager、Taro Storage Adapter、AuthContext、登录守卫、受控登录表单和账号密码注册页均已实现。登录链已于 2026-08-20 完成微信 Functional；注册补漏项于 2026-08-25 完成工程实现与微信 Functional。注册成功只创建普通用户，不自动登录；非幂等 POST 的未知结果不自动重发。该结果不代表真机、H5、正式 HTTPS/合法域名或微信登录通过。详细复盘见 [Phase 5 登录纵向链路学习笔记](learning_notes/phase5_auth_vertical_slice.md)与[账号密码注册补漏学习笔记](learning_notes/phase5_account_registration.md)。

学习：

- `useEffect` 和依赖数组；
- 清理函数与请求竞态；
- Taro 页面生命周期；
- Context；
- Storage；
- 登录守卫；
- 派生状态与重复状态；
- 敏感信息。

实践：登录、注册、恢复 Session、`/users/me`、登出、普通入口与 ADMIN 入口均已完成；注册成功不自动登录，ADMIN 最终授权仍由后端执行。

注意：Effect 只处理副作用；能在 render/事件中算出的值不放 Effect；Context 不承载所有业务数据；密码不持久化。

---

## 9. 阶段 6：Product 与 UI 状态

> **阶段状态：已完成并通过自动化与微信 Functional。** `ProductApi.listProducts()`、运行时 Guard、相对图片 Resolver、分页 Feature、公开首页四态、Product type 和 300ms keyword 防抖已实现；2026-08-22 已人工验证 Content、相对图片、第二页、筛选/组合搜索/Empty。Experience/Kit 详情 Endpoint、动态路由、详情状态、Kit 库存展示和真实 Option 组合选择均已完成；local-only Seed 提供一条带两个不同组合、价格和配色图片的 Experience，并通过正式 Inventory 流水让一条 Kit 初始库存为 8、另外五条保持 0。20 项 Seed 隔离测试、前端 11 套件/70 项、静态检查、OpenAPI 漂移和四端生产构建均通过，详见 [列表学习笔记](learning_notes/phase6_product_list.md)和[详情学习笔记](learning_notes/phase6_product_detail.md)。

学习：

- 分页；
- 搜索防抖；
- 请求竞态；
- Loading/Empty/Error/Content；
- 派生状态；
- 有效组合而不是无约束笛卡尔积；
- 图片和响应式布局。

实践：公开 Product 列表与搜索/筛选、Experience/Kit 详情与 Option 选择（均已完成）。

完成标准：只允许选择真实 Option；Kit stock 只用于展示；旧查询不会覆盖新筛选。

---

## 10. 阶段 7：Order、状态机和幂等

> **阶段状态：Phase 7.1–7.4 的工程实现、自动化与微信开发者工具 Functional 均已完成。** 7.1 已实现判别联合 Cart、版本化 Storage 和串行 mutation；7.2 已实现确认/创建、unknown 分流、服务端快照与保守 Cart 对账；7.3 已实现用户列表/详情/Pending cancel 和状态收敛；7.4 已实现 `admin` 分包、ADMIN+ 完整订单筛选/详情、Pending → Paid、Paid → Completed、前后端权限边界和命令结果收敛。2026-08-25 用户确认 7.3/7.4 两类 40921 独立客户端竞态、7.4 断网 unknown 不重发、普通用户 ADMIN API 403/不 refresh 及其余人工清单全部通过；Slow 3G 约 310 ms 返回、未触发 timeout，严格 timeout 保留为非阻断补测。完整前端 31 套件/213 项、静态检查、OpenAPI 漂移与四端 production build 通过，Order API 后端回归 107 项及完整后端 1445 项通过（9 项 MySQL-only 跳过）。详见[本地购物车学习笔记](learning_notes/phase7_local_cart.md)、[创建订单学习笔记](learning_notes/phase7_order_create.md)、[订单查询/取消学习笔记](learning_notes/phase7_order_query_cancel.md)和[ADMIN 订单操作学习笔记](learning_notes/phase7_admin_order_operations.md)。

学习：

- 本地缓存与服务端权威；
- Snapshot；
- 状态机；
- 乐观/保守更新；
- 幂等键；
- 网络结果未知；
- 防重复提交。
- 角色入口与服务端授权；
- 排他时间上界；
- 小程序分包。

实践：本地购物车（7.1）、确认与创建（7.2）、用户列表/详情/取消（7.3）、ADMIN 列表/详情/人工支付与完成（7.4）均已完成并通过对应微信开发者工具 Functional。下一步进入 Phase 8，先冻结第一条 ADMIN Product 最小纵向切片。

完成标准：不伪造 Paid；不重复组合；不自动重试无幂等的 Order create；金额只用后端快照。

---

## 11. 阶段 8：Admin、上传与权限

> **阶段规划已冻结。** Phase 8 以现有 FastAPI 能力为上限，采用“先建立安全读模型，再逐步开放 mutation”的顺序。8.1 ADMIN Product 只读管理纵向切片已实现并完成现有数据范围内的微信开发者工具 Functional；后续写操作与发布门槛按下表逐阶段验收。

学习：

- 分包；
- 角色入口与后端授权；
- multipart；
- 客户端/服务端文件校验；
- 复杂表单拆分；
- Product readiness issues；
- Inventory Idempotency-Key；
- Audit Log。

实施顺序：

| 子阶段 | 工程交付 | 关键边界 | 状态 |
|--------|----------|----------|------|
| 8.1 | ADMIN Product 列表、筛选、分页与 Experience/Kit 管理详情 | 草稿允许空封面/价格/Option；逻辑删除可查；普通用户不挂载管理 Hook；后端 ADMIN+ 最终授权 | 已完成，含完整微信 Functional |
| 8.2 | Experience/Kit 创建与基本信息编辑、逻辑删除 | 复杂表单按 Product 类型拆分；PATCH 只发送改动字段；删除只服从后端前置条件 | 已完成，含业务 Functional；延期的管理页白色图案与登录 `_` 闪烁已于 2026-08-29 复测关闭 |
| 8.3 | Experience Option 与 Kit 价格管理 | Option 全历史组合唯一与恢复原 ID；Kit 无 Option；历史订单快照不被覆盖 | 工程实现、自动化及可验收微信 Functional 已完成；改价前后订单快照联动现已纳入 8.4–8.5 Functional |
| 8.4 | Product/Option 图片上传、排序、封面与删除 | multipart；2 MiB/jpg/png/webp 双端校验；部分成功可恢复；相对 URL | 已完成，含完整微信 Functional |
| 8.5 | 上下架与 readiness issues | online 使用 empty-body PATCH；`42201.data.issues` 一次完整展示；不在客户端复制 Validator | 已完成，含微信 Functional 与 8.3 新旧订单快照联动 |
| 8.6 | Kit Inventory 调整与两类流水查询 | 每次业务意图生成 key，同次重试复用；首次 201/重放 200；不泄露 key | 已完成，含工程门槛与完整微信 Functional |
| 8.7 | Order 管理整合 | 复用已完成的 7.4 查询、Paid/Completed 与 unknown/40921 收敛，不重复造状态编辑器 | 由 7.4 完成，Phase 8 只做导航整合 |
| 8.8 | Product Audit 与 ADMIN User 列表/禁用 | 审计只读白名单；用户能力只做现有列表/禁用，不提供尚不存在的启用/详情/头像按钮 | 已完成，含完整微信 Functional |
| 8.9 | 管理端整体 Review 与多端门槛 | 权限、上传、幂等、隐私、包体、微信 Functional、四端 Build 和真实后端回归 | 当前后端能力范围的工程 Review、自动门槛与微信 Functional 均完成；8.2 两项延期视觉问题已于 2026-08-29 关闭 |

8.1 明确不包含创建、编辑、删除、Option mutation、图片上传、上下架、库存调整或审计；详情页显示“只读”说明，避免按钮暗示尚未交付的能力。后续每个 mutation 子阶段都必须先冻结请求、成功、失败、unknown/幂等与恢复语义，再开放 UI。

8.3 的端点、状态机、页面、自动化、知识点与微信验收清单见 [Phase 8.3 学习笔记](learning_notes/phase8_admin_product_configuration.md)。

8.4–8.5 的 multipart 上传适配、图片生命周期、readiness/状态机、结果未知恢复、知识点与合并微信验收清单见 [Phase 8.4–8.5 学习笔记](learning_notes/phase8_admin_product_images_status.md)。

8.6 的 Kit 库存调整、HTTP 201/200 metadata、业务意图幂等、两类流水筛选分页、知识点与微信验收清单见 [Phase 8.6 学习笔记](learning_notes/phase8_admin_inventory.md)。

8.8–8.9 的 Product Audit、ADMIN User 契约收口、禁用事务/旧 Token 阻断、总体 Review、知识点与微信验收清单见 [Phase 8.8–8.9 学习笔记](learning_notes/phase8_admin_audit_users_review.md)。

完成标准：普通用户 403；上传/库存错误可解释；同次库存重试复用 key；不存在的后端功能没有按钮。

---

## 12. 阶段 9：微信、CI 与发布

> **本版范围已冻结为微信小程序。** 第一交付目标是受控的内部微信测试版；通过后再以独立 Go/No-Go 门决定是否进入对外公开发布。支付宝、抖音和 H5 不属于本版 CI 阻断项、Functional 矩阵或发布承诺，已有跨端源码与构建能力只作为未来兼容基础保留。Phase 9.1 仓库级证据、八类控制文档、责任人映射和项目负责人 Review 已完成，当前进入 9.2；完整范围见 [Phase 9 微信小程序发布规划](phase9_wechat_release_plan.md)，可执行审计与清单见 [Phase 9 发布文档](../09_release/README.md)。

学习：

- HTTPS、DNS、证书与微信 request/upload/download 合法域名；
- AppID 与 AppSecret、前端公开配置与后端 Secret 的边界；
- Build、Smoke、Functional、E2E 与真机证据的区别；
- CI、锁文件、不可变 artifact、Git SHA 与可重复构建；
- MySQL 迁移、备份恢复、前滚修复与应用回滚的区别；
- liveness/readiness、日志脱敏、监控、告警和事故响应；
- 微信登录、账号绑定、支付通知、服务端幂等和未知结果；
- 隐私保护指引、用户权利、平台审核和发布授权。

| 子阶段 | 实践 | 完成标准 |
|--------|------|----------|
| 9.1 | 冻结微信单平台、Gate A 内部测试版与 Gate B 公开版；审计配置、CI、迁移、测试和风险 | **已完成（2026-08-29）**：Yijie Shen 已确认范围、责任和关闭 Gate；不代表 Gate A Ready |
| 9.2 | 建立后端 SQLite、MySQL-only、前端质量、OpenAPI、微信构建、生成物/Secret/依赖审计 CI | 干净 checkout 可重复通过，artifact 绑定 Git SHA |
| 9.3 | 在可销毁的生产相似环境完成 0→当前、受支持升级、备份恢复、失败处置和完整 Smoke | 迁移、恢复、FastAPI、Redis、图片、管理员初始化、健康检查均有证据 |
| 9.4 | 上传受控微信体验版并在 iOS/Android 完成弱网、前后台、上传和角色 Functional | Gate A 全部通过，版本仍明确不可公开 |
| 9.5 | 完成微信身份、账号关联、认证强化、Secret、存储、监控和隐私基线 | Gate B 的身份、安全、运维与合规项全部通过 |
| 9.6 | 仅在公开版在线成交/收款时完成 Order create 幂等与微信支付/退款/对账 | 金额、签名、通知幂等、重复/延迟/未知结果和退款对账通过 |
| 9.7 | 冻结公开 RC、提审、发布后观察与回滚准备 | Gate B 全部通过并取得明确发布授权 |

当前进入 9.2 CI 与可重复构建。9.1 已完成但未直接实现微信支付、未迁移持久数据库、未修改微信后台，也未上传或发布任何版本；Gate A 继续保持 No-Go，直到 9.2–9.4 的证据全部通过。

阶段完成标准以 [Phase 9 微信小程序发布规划](phase9_wechat_release_plan.md) 的 Gate A/Gate B 和[测试策略](testing_strategy.md)为准。

---

## 13. 依赖引入学习规则

每次想增加包时回答：

1. 标准库、React、Taro 或现有依赖能否完成？
2. 它解决的是已发生问题还是假想问题？
3. 微信/支付宝/抖音/H5 是否支持？
4. 维护、许可证、体积和传递依赖如何？
5. 如何测试和移除？
6. 是否需要 ADR？

不能回答时先不引入。

---

## 14. 学习完成的判断

对一个知识点“学会”至少意味着：

- 能用自己的话解释；
- 能写一个最小例子；
- 能写失败/边界测试；
- 能读懂常见报错；
- 知道它属于哪一层；
- 知道何时不该使用；
- 能在不复制旧实现的情况下完成一个相似任务。
